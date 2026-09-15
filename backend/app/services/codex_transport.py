"""Bounded stdio JSON-RPC bridge to an app-owned Codex process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import tempfile
import time


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
        # The app keeps the durable auth.json in ``home``.  Codex app-server
        # also creates several SQLite state databases under CODEX_HOME; using
        # the auth directory directly makes it collide with a running desktop
        # Codex process.  Give each bridge its own runtime directory and
        # expose only the persisted auth file to it.
        self.runtime_home: Path | None = None
        self._runtime_auth_is_copy = False
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
            if self.runtime_home is None:
                self._cleanup_stale_runtime_homes()
                self.runtime_home = Path(tempfile.mkdtemp(prefix='storyguard-codex-'))
                self.runtime_home.chmod(0o700)
            auth_file = self.home / 'auth.json'
            runtime_auth = self.runtime_home / 'auth.json'
            if auth_file.exists() and not runtime_auth.exists():
                try:
                    runtime_auth.symlink_to(auth_file)
                    self._runtime_auth_is_copy = False
                except OSError:
                    # Windows may not permit symlink creation.  The fallback
                    # is synchronized back in close(), preserving login state.
                    shutil.copy2(auth_file, runtime_auth)
                    runtime_auth.chmod(0o600)
                    self._runtime_auth_is_copy = True
            process = subprocess.Popen(
                [find_codex(), 'app-server', '-c', 'cli_auth_credentials_store="file"',
                 '-c', 'forced_login_method="chatgpt"'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', bufsize=1, cwd=str(self.runtime_home),
                env=isolated_environment(self.runtime_home),
            )
            self._process = process
            threading.Thread(target=self._read, args=(process,), daemon=True).start()
            try:
                self.request('initialize', {'clientInfo': {'name': 'story_guard', 'title': 'Story Guard', 'version': '0.1.0'}}, timeout=15, start=False)
                self._send({'method': 'initialized', 'params': {}})
            except Exception:
                self.close()
                raise RuntimeError('Codex app-server 초기화에 실패했습니다. 실행 파일 버전과 설치 상태를 확인해 주세요.') from None

    @staticmethod
    def _cleanup_stale_runtime_homes(max_age_seconds: int = 12 * 60 * 60) -> None:
        """Remove abandoned app-server sandboxes left by a crash or force quit.

        Normal shutdown already removes ``runtime_home``.  A killed process
        cannot run ``close()``, however, so its PyInstaller/Codex state would
        otherwise accumulate in the system temp directory on every retry.
        Only our own prefix and entries older than the safety window are
        touched; a currently running server gets a fresh directory and is not
        eligible during ordinary analysis runs.
        """
        temp_root = Path(tempfile.gettempdir())
        now = time.time()
        for candidate in temp_root.glob('storyguard-codex-*'):
            try:
                if not candidate.is_dir() or now - candidate.stat().st_mtime < max_age_seconds:
                    continue
                shutil.rmtree(candidate, ignore_errors=True)
            except OSError:
                continue

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
        if self._runtime_auth_is_copy and self.runtime_home is not None:
            runtime_auth = self.runtime_home / 'auth.json'
            auth_file = self.home / 'auth.json'
            if runtime_auth.exists():
                temporary = auth_file.with_suffix('.json.tmp')
                shutil.copy2(runtime_auth, temporary)
                temporary.chmod(0o600)
                temporary.replace(auth_file)
            self._runtime_auth_is_copy = False
        if self.runtime_home is not None:
            shutil.rmtree(self.runtime_home, ignore_errors=True)
            self.runtime_home = None
        self._process = None
