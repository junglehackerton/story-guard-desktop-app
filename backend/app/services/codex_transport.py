"""Bounded stdio JSON-RPC bridge to an app-owned Codex process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading


def isolated_environment(home: Path) -> dict[str, str]:
    allowed = {'PATH', 'HOME', 'USER', 'TMPDIR', 'TEMP', 'TMP', 'SYSTEMROOT', 'WINDIR', 'LOCALAPPDATA', 'APPDATA', 'LANG', 'LC_ALL'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env['CODEX_HOME'] = str(home)
    return env


def find_codex() -> str:
    configured = os.getenv('STORY_GUARD_CODEX_BIN')
    candidates = [configured] if configured else [
        '/Applications/ChatGPT.app/Contents/Resources/codex',
        '/Applications/Codex.app/Contents/Resources/codex',
        shutil.which('codex'),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError('Codex 실행 파일이 없습니다. app-server를 지원하는 Codex를 설치하거나 STORY_GUARD_CODEX_BIN을 지정해 주세요.')


class CodexTransport:
    def __init__(self, home: Path):
        self.home = home
        self.callback = lambda method, params: None
        self._process = None
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending = {}
        self._next_id = 0
        self._start_lock = threading.RLock()

    def start(self):
        with self._start_lock:
            if self._process is not None and self._process.poll() is None:
                return
            self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            process = subprocess.Popen(
                [find_codex(), 'app-server', '-c', 'cli_auth_credentials_store="file"',
                 '-c', 'forced_login_method="chatgpt"'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', bufsize=1, cwd=str(self.home),
                env=isolated_environment(self.home),
            )
            self._process = process
            threading.Thread(target=self._read, args=(process,), daemon=True).start()
            try:
                self.request('initialize', {'clientInfo': {'name': 'story_guard', 'title': 'Story Guard', 'version': '0.1.0'}}, timeout=15, start=False)
                self._send({'method': 'initialized', 'params': {}})
            except Exception:
                self.close()
                raise RuntimeError('Codex app-server 초기화에 실패했습니다. 실행 파일 버전과 설치 상태를 확인해 주세요.') from None

    def _send(self, message):
        with self._write_lock:
            process = self._process
            if process is None or process.poll() is not None:
                raise RuntimeError('Codex 연결이 종료되었습니다.')
            process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            process.stdin.flush()

    def request(self, method, params=None, timeout=30, start=True):
        if start:
            self.start()
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            result_queue = queue.Queue(maxsize=1)
            self._pending[request_id] = result_queue
        try:
            self._send({'id': request_id, 'method': method, 'params': params or {}})
            try:
                response = result_queue.get(timeout=timeout)
            except queue.Empty:
                # A wedged app-server cannot reliably service later retries.
                # Tear it down so the caller's bounded retry can start a fresh
                # process instead of repeatedly waiting on the same dead one.
                if method != 'initialize':
                    self.close()
                raise RuntimeError(f'Codex 응답 시간이 초과되었습니다: {method}') from None
            if 'error' in response:
                # Do not expose upstream payloads, credentials or prompts to the UI/logs.
                raise RuntimeError(f'Codex 요청 실패: {method} (code={response["error"].get("code", "unknown")})')
            return response.get('result', {})
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def _read(self, process):
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if 'id' in message and 'method' not in message:
                    with self._lock:
                        target = self._pending.get(message['id'])
                        if target is not None and not target.full():
                            target.put_nowait(message)
                elif 'method' in message and 'id' in message:
                    self._send({'id': message['id'], 'error': {'code': -32601, 'message': 'Interactive tools are not supported by Story Guard.'}})
                elif 'method' in message:
                    self.callback(message['method'], message.get('params', {}))
        finally:
            with self._lock:
                for target in self._pending.values():
                    if not target.full():
                        target.put_nowait({'error': {'code': 'process_exited'}})

    def close(self):
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        self._process = None
