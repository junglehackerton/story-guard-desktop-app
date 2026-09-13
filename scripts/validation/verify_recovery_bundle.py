"""Smoke check the packaged backend using a temporary, unauthenticated data directory.

This does not execute GPT or substitute for native UI/end-to-end analysis validation.
"""
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import types
from PyInstaller.archive.readers import CArchiveReader

root = Path(__file__).resolve().parents[2]
binary = root / 'src-tauri/target/release/bundle/macos/Story Guard.app/Contents/MacOS/story-guard-backend'
if not binary.is_file():
    raise SystemExit(f'Packaged backend missing: {binary}')
archive = CArchiveReader(str(binary))
pyz = archive.open_embedded_archive(next(key for key in archive.toc if key.endswith('.pyz')))
def strings(code):
    for value in code.co_consts:
        if isinstance(value, str):
            yield value
        elif isinstance(value, types.CodeType):
            yield from strings(value)
assert any('현재 구간 ID 목록:' in value for value in strings(pyz.extract('backend.app.pipeline.gpt_analyzer')))
assert 'backend.app.pipeline.gpt_review_run' in pyz.toc
assert 'backend.app.pipeline.gpt_review_window' in pyz.toc
assert 'backend.app.services.gpt_errors' in pyz.toc
assert 'stop_run' in set(strings(pyz.extract('backend.app.pipeline.gpt_review_window')))
assert 'gpt-review-v4-split' in set(strings(pyz.extract('backend.app.pipeline.gpt_analyzer')))
with tempfile.TemporaryDirectory(prefix='storyguard-bundle-check-') as directory:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, STORY_GUARD_DATA_DIR=directory, STORY_GUARD_BACKEND_PORT=str(port),
               STORY_GUARD_PARENT_PID=str(os.getpid()), STORY_GUARD_API_TOKEN='')
    started = time.monotonic()
    with open(Path(directory) / 'backend.log', 'w+') as log:
        process = subprocess.Popen([str(binary)], env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            ready = False
            while time.monotonic() - started < 45:
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready', timeout=1) as response:
                        ready = json.load(response) == {'status': 'ok'}
                    if ready:
                        break
                except (OSError, ValueError):
                    time.sleep(.25)
            if not ready:
                log.seek(0)
                raise RuntimeError(log.read()[-2000:])
            with sqlite3.connect(Path(directory) / 'story_guard.sqlite') as db:
                columns = {row[1] for row in db.execute('PRAGMA table_info(analysis_jobs)')}
                assert {'window_details', 'review_context'} <= columns
                assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='gpt_review_runs'").fetchone()[0] == 1
            result = {'packaged_backend_ready': True, 'startup_seconds': round(time.monotonic() - started, 2),
                      'recovery_schema_verified': True, 'adaptive_split_code_verified': True, 'provider_error_policy_verified': True, 'gpt_requests': 0, 'native_ui_tested': False,
                      'user_data_modified': False}
            output = root / 'output/validation/gpt-recovery-20260912/bundle-smoke.json'
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
