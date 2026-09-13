"""Durable review checkpoints, private responses and public window diagnostics."""
import hashlib
import json
import time


class GptReviewRun:
    def __init__(self, database, job_id, project_id, source, windows, doc_names, model, effort, force,
                 start_chapter=None, end_chapter=None):
        self.database, self.job_id = database, job_id
        self.started = {}
        self.window_keys = [self.window_key(row) for row in windows]
        # Model/effort/schema/settings changes invalidate old responses, while
        # adding a new chapter should leave unchanged windows reusable.
        compatibility = [source[0], source[1], source[2], source[3], source[6] if len(source) > 6 else []]
        self.compatibility_key = hashlib.sha256(json.dumps(compatibility, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.details = [dict(index=i + 1, chunk_id=row['id'], document=doc_names[row['document_id']],
                             status='queued', stage='queued', attempts=0, elapsed_seconds=0, error='')
                        for i, row in enumerate(windows)]
        snapshot = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with database.connect() as db:
            previous = None if force else db.execute(
                'SELECT checkpoints FROM gpt_review_runs WHERE project_id=? ORDER BY job_id DESC LIMIT 1',
                (project_id,)).fetchone()
            raw = json.loads(previous['checkpoints']) if previous else {}
            self.checkpoints = {}
            if raw.get('__meta__', {}).get('compatibility_key') == self.compatibility_key:
                # Preserve both whole-window and split-leaf checkpoints. A
                # single window can have several `index:path` entries.
                key_to_index = {key: index for index, key in enumerate(self.window_keys)}
                for stored_key, item in raw.items():
                    if stored_key == '__meta__' or not isinstance(item, dict):
                        continue
                    window_key = item.get('window_key')
                    index = key_to_index.get(window_key)
                    if index is None:
                        continue
                    path = item.get('part_path')
                    checkpoint_key = f'{index}:{path}' if ':' in stored_key and path else str(index)
                    self.checkpoints[checkpoint_key] = {k: v for k, v in item.items()
                                                        if k not in ('window_key', 'part_path')}
            elif previous and snapshot == db.execute(
                'SELECT snapshot_key FROM gpt_review_runs WHERE project_id=? ORDER BY job_id DESC LIMIT 1',
                (project_id,)).fetchone()['snapshot_key']:
                # Legacy exact-snapshot checkpoints had no metadata.
                self.checkpoints = {key: value for key, value in raw.items() if key != '__meta__'}
            self.checkpoints['__meta__'] = {'compatibility_key': self.compatibility_key}
            db.execute('INSERT INTO gpt_review_runs(job_id,project_id,snapshot_key,checkpoints) VALUES(?,?,?,?)',
                       (job_id, project_id, snapshot, json.dumps(self.checkpoints, ensure_ascii=False)))
            db.execute('UPDATE analysis_jobs SET window_details=?,review_context=? WHERE id=?',
                       (json.dumps(self.details, ensure_ascii=False), json.dumps({'model': model, 'effort': effort,
                           'start_chapter': start_chapter, 'end_chapter': end_chapter}), job_id))

    @staticmethod
    def window_key(row):
        payload = {'chunk_ids': row.get('_chunk_ids', [row['id']]), 'text': row['text']}
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def get(self, index):
        return self.checkpoints.get(str(index))

    def update(self, index, **changes):
        self.started.setdefault(index, time.monotonic())
        self.details[index].update(changes, elapsed_seconds=round(time.monotonic() - self.started[index], 2))
        detail = self.details[index]
        with self.database.connect() as db:
            cursor = db.execute("""UPDATE analysis_jobs SET window_details=?,updated_at=CURRENT_TIMESTAMP,
                current_step=?,message=? WHERE id=? AND status='running'""",
                (json.dumps(self.details, ensure_ascii=False), 'gpt_' + detail['stage'],
                 f"{detail['document']} · {index + 1}/{len(self.details)} 구간 · {detail['stage']}"
                 + (f" · {detail['error']}" if detail['error'] else ''), self.job_id))
            if cursor.rowcount != 1:
                raise RuntimeError('GPT 분석이 취소되었습니다.')
            db.execute('UPDATE gpt_review_runs SET checkpoints=? WHERE job_id=?',
                       (json.dumps(self.checkpoints, ensure_ascii=False), self.job_id))

    def save(self, index, response, evidence_ids, reused=False):
        self.checkpoints[str(index)] = {'response': response, 'evidence_ids': evidence_ids,
                                        'window_key': self.window_keys[index]}
        self.update(index, status='completed', stage='validated', reused=reused, error='')

    def discard(self, index):
        self.checkpoints.pop(str(index), None)

    def get_part(self, index, path):
        if not path:
            return self.get(index)
        return self.checkpoints.get(f'{index}:{path}')

    def split_part(self, index, path):
        key = f'{index}:{path}' if path else str(index)
        self.checkpoints[key] = {'split': True, 'window_key': self.window_keys[index], 'part_path': path}
        self.update(index, stage='split')

    def part_status(self, index, path, ids, status, error='', **changes):
        parts = self.details[index].setdefault('parts', [])
        part = next((part for part in parts if part['path'] == path), None)
        if part is None:
            part = {'path': path, 'chunk_ids': ids}
            parts.append(part)
        timer_key = (index, path)
        self.started.setdefault(timer_key, time.monotonic())
        part.update(status=status, error=error, elapsed_seconds=round(time.monotonic() - self.started[timer_key], 2), **changes)
        self.update(index)

    def save_part(self, index, path, response, evidence_ids, ids, reused):
        key = f'{index}:{path}' if path else str(index)
        self.checkpoints[key] = {'response': response, 'evidence_ids': evidence_ids,
                                 'window_key': self.window_keys[index], 'part_path': path}
        self.part_status(index, path, ids, 'completed', reused=reused)

    def discard_part(self, index, path):
        self.checkpoints.pop(f'{index}:{path}' if path else str(index), None)
