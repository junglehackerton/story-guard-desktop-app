"""Verify packaged startup/cancellation against disposable data, without GPT requests."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

# Allow the validator to be run directly from the repository root or from any
# shell working directory, matching the other validation entry points.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import Database
from backend.app.repository import StoryRepository


root = ROOT
binary = root / 'src-tauri/target/release/bundle/macos/Story Guard.app/Contents/MacOS/story-guard-backend'
output = root / 'output/validation/analysis-interruption-20260912/bundle-check.json'
details = [dict(index=i + 1, chunk_id=i + 1, document=f'{i + 1}화', status=status,
                stage='wait', attempts=1 if i < 2 else 0, elapsed_seconds=4, error='')
           for i, status in enumerate(['completed', 'running', 'queued'])]
context = {'model': 'luna', 'effort': 'medium'}

with tempfile.TemporaryDirectory(prefix='storyguard-interruption-bundle-') as directory:
    repo = StoryRepository(Database(Path(directory) / 'story_guard.sqlite'))
    project = repo.create_project('패키지 중단 복구 시험')
    issue = repo.add_issue(project.id, 'low', 'contradiction', '보존할 이전 후보', '시험용 수동 후보', [])
    repo.update_issue_status(issue.id, 'deferred')

    def create_pending():
        job = repo.create_running_analysis_job(project.id, '시험용 응답 대기', 'gpt_wait', 42, review_context=context)
        with repo.database.connect() as db:
            db.execute('UPDATE analysis_jobs SET window_details=? WHERE id=?', (json.dumps(details), job.id))
            db.execute('INSERT INTO gpt_review_runs(job_id,project_id,snapshot_key,checkpoints) VALUES(?,?,?,?)',
                       (job.id, project.id, 'test-snapshot', '{"saved":"checkpoint"}'))
        return job

    first = create_pending()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, STORY_GUARD_DATA_DIR=directory, STORY_GUARD_BACKEND_PORT=str(port),
               STORY_GUARD_PARENT_PID=str(os.getpid()), STORY_GUARD_API_TOKEN='')

    def request(path, method='GET'):
        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', method=method)
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.load(response)

    def assert_closed(job, status):
        assert job['status'] == status and job['progress'] == 42
        assert [window['status'] for window in job['window_details']] == ['completed', 'interrupted', 'deferred']
        assert job['review_context'] == context
        with repo.database.connect() as db:
            assert db.execute('SELECT checkpoints FROM gpt_review_runs WHERE job_id=?', (job['id'],)).fetchone()[0] == '{"saved":"checkpoint"}'

    started = time.monotonic()
    with open(Path(directory) / 'backend.log', 'w+') as log:
        process = subprocess.Popen([str(binary)], env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            ready = False
            while time.monotonic() - started < 45 and process.poll() is None:
                try:
                    ready = request('/health/ready') == {'status': 'ok'}
                    if ready:
                        break
                except (OSError, ValueError):
                    time.sleep(.25)
            if not ready:
                log.seek(0)
                raise RuntimeError(log.read()[-1800:])
            startup_seconds = round(time.monotonic() - started, 2)
            restored = request(f'/projects/{project.id}/analysis/status')
            assert restored['id'] == first.id
            assert_closed(restored, 'failed')
            second = create_pending()
            cancelled = request(f'/projects/{project.id}/analysis/cancel', 'POST')
            assert cancelled['id'] == second.id
            assert_closed(cancelled, 'cancelled')
            assert request(f'/projects/{project.id}/analysis/cancel', 'POST') == cancelled
            graph = request(f'/projects/{project.id}/graph')
            assert graph['issues'][0]['id'] == issue.id and graph['issues'][0]['status'] == 'deferred'
            result = dict(packaged_backend_ready=True, startup_seconds=startup_seconds,
                          interrupted_windows_closed=True, cancelled_windows_closed=True,
                          original_progress_preserved=True, model_effort_preserved=True,
                          checkpoints_preserved=True, author_judgment_preserved=True,
                          repeated_cancel_unchanged=True, gpt_requests=0,
                          native_ui_tested=False, original_user_database_changed=False)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
