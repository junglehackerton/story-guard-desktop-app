"""Export only the public Baekro sample from a read-only desktop database."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--database', type=Path, required=True)
p.add_argument('--project', type=int, required=True)
a = p.parse_args()
c = sqlite3.connect(f'{a.database.resolve().as_uri()}?mode=ro', uri=True)
c.row_factory = sqlite3.Row
c.execute('BEGIN')
def rows(table):
    return [dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE project_id=?', (a.project,))]
project = dict(c.execute('SELECT * FROM projects WHERE id=?', (a.project,)).fetchone())
assert project['title'] == '백로호텔의 마지막 손님', 'Only the approved public sample can be exported'
documents = sorted(rows('documents'), key=lambda d: d['chapter_index'])
assert len(documents) == 10
for d in documents:
    sample = root / 'samples/baekro-hotel' / f"episode-{d['chapter_index']+1:02}.txt"
    assert sample.read_text().strip() == d['content'].strip(), f'Sample mismatch: {sample.name}'
    d.update(path=sample.name, analysis_status='analyzed', analyzed_at=None, analysis_entity_count=0,
             analysis_relation_count=0, analysis_claim_count=0)
chunks = rows('chunks')
by_doc = {d['id']: d for d in documents}
for ch in chunks:
    assert ch['text'] in by_doc[ch['document_id']]['content'], f"Invalid evidence {ch['id']}"
entities = rows('entities')
for e in entities:
    e['aliases'] = json.loads(e['aliases'])
    ids = [d['id'] for d in documents if any(t and t in d['content'] for t in [e['name'], *e['aliases']])]
    e.update(document_ids=ids, document_count=len(ids), mention_count=sum(d['content'].count(e['name']) for d in documents),
             last_seen_document_id=ids[-1] if ids else None, appearance_state='active', visual_weight=.6,
             is_unresolved=bool(e.get('is_unresolved')))
relations = rows('relations')
chunk_ids = {ch['id'] for ch in chunks}
entity_ids = {e['id'] for e in entities}
for r in relations:
    r['evidence_chunk_ids'] = json.loads(r['evidence_chunk_ids'])
    r['claims'] = json.loads(r['claims'] or '[]')
    assert set(r['evidence_chunk_ids']) <= chunk_ids
    assert {r['source_entity_id'], r['target_entity_id']} <= entity_ids
    # Drop invalid quoted claims rather than publish approximate source evidence.
    for claim in r['claims']:
        claim['quotes'] = [q for q in claim.get('quotes', []) if q.get('document_id') in by_doc and q.get('quote') and q['quote'] in by_doc[q['document_id']]['content']]
    r.update(strength=r['confidence'], is_weak=r['confidence']<.5 or r['type']=='co_occurs',
             is_recent=True, display_label='' if r['type']=='co_occurs' else r['type'])
issues = rows('issues')
for i in issues:
    i['evidence_chunk_ids'] = json.loads(i['evidence_chunk_ids'])
    assert set(i['evidence_chunk_ids']) <= chunk_ids
    i['status'] = 'open'
project.update(root_path=None, document_count=len(documents), pending_document_count=0, open_issue_count=len(issues))
# No local paths, account settings, authentication, jobs or request caches are exported.
data = dict(project=project, documents=documents, chunks=chunks, graph=dict(entities=entities, relations=relations, issues=issues, changes=[],
    range=dict(start_chapter=0,end_chapter=9,document_ids=list(by_doc),document_count=10,continuity_ready=True,message='전체 10화')),
    provenance='데스크톱 앱의 실제 분석 결과 · 공개 샘플 원문 대조 완료')
data['version'] = hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
(root/'src/demo/snapshot.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
print(f"Exported {len(documents)} chapters, {len(chunks)} chunks, {len(entities)} entities, {len(relations)} relations, {len(issues)} issues; version {data['version']}")
