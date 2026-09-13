from __future__ import annotations

import atexit
from pathlib import Path
import queue
import threading
import time
import webbrowser

from backend.app.services.gpt_errors import provider_error
from backend.app.services.codex_transport import CodexTransport, isolated_environment

VERIFICATION_URL = 'https://auth.openai.com/codex/device'
CHECK_PROMPT = '''다음은 연결 검증을 위한 가상의 원고입니다. 도구나 파일을 사용하지 말고 제공된 문장만 분석하세요.
1화 규칙: 계약자만 봉인검을 사용할 수 있다.
2화: 유나는 계약을 거절했다.
6화: 유나는 스승과 정식으로 계약을 맺었다.
7화: 유나는 봉인검을 사용했다.
계약 규칙 위반이라고 단정할 수 있는지 한국어로 3문장 이내로 설명하고 근거 회차를 적으세요.'''


class ChatGptConnection:
    def __init__(self, data_dir: Path, transport=None):
        self.home = data_dir / 'chatgpt-auth'
        self.transport = transport or CodexTransport(self.home)
        self.transport.callback = self.on_notification
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self._login_id = None
        self._deadline = None
        self._code = None
        self._error = None
        self._events = None
        self._phase = 'disconnected'
        self._models_cache = None
        self._models_cache_at = 0.0
        atexit.register(self.transport.close)

    def on_notification(self, method, params):
        with self._lock:
            if method == 'account/login/completed' and params.get('loginId') == self._login_id and self._login_id:
                self._phase = 'disconnected' if params.get('success') else 'failed'
                self._error = None if params.get('success') else '인증이 완료되지 않았습니다. 다시 연결해 주세요.'
                self._login_id = self._code = self._deadline = None
            if self._events is not None and method in {'item/completed', 'turn/completed', 'error'}:
                self._events.put((method, params))

    def status(self):
        with self._operation:
            if self._deadline and time.monotonic() >= self._deadline:
                self._cancel()
                self._phase = 'expired'
            try:
                # Read the local persisted session first. Refreshing the
                # subscription token can block on network/provider state and
                # should never delay the app's ordinary status check.
                try:
                    account = self.transport.request('account/read', {'refreshToken': False}, timeout=10).get('account')
                except RuntimeError:
                    account = self.transport.request('account/read', {'refreshToken': True}, timeout=10).get('account')
                connected = bool(account and account.get('type') == 'chatgpt')
                if connected:
                    if self._phase != 'connected':
                        self._models_cache = None
                        self._models_cache_at = 0.0
                    self._phase = 'connected'
                    self._code = self._login_id = self._deadline = None
                    self._error = None
                elif self._phase == 'connected':
                    self._phase = 'disconnected'
                if account and account.get('type') != 'chatgpt':
                    self._error = 'ChatGPT 계정 로그인이 필요합니다. API 키 인증은 사용하지 않습니다.'
                return {'phase': self._phase, 'user_code': self._code,
                        'verification_url': VERIFICATION_URL if self._code else None,
                        'plan': account.get('planType') if connected else None,
                        'error': self._error}
            except RuntimeError as error:
                return {'phase': 'unavailable', 'user_code': None, 'verification_url': None,
                        'plan': None, 'error': str(error)}

    def login(self):
        with self._operation:
            self._models_cache = None
            self._models_cache_at = 0.0
            if self._login_id and self._deadline and self._deadline > time.monotonic():
                return self._pending_state()
            response = self.transport.request('account/login/start', {'type': 'chatgptDeviceCode'})
            if response.get('verificationUrl') != VERIFICATION_URL:
                if response.get('loginId'):
                    self.transport.request('account/login/cancel', {'loginId': response['loginId']})
                raise RuntimeError('OpenAI 인증 주소를 확인하지 못했습니다.')
            if not response.get('loginId') or not response.get('userCode'):
                raise RuntimeError('기기 인증 코드를 받지 못했습니다.')
            with self._lock:
                self._login_id = response['loginId']
                self._code = response['userCode']
                self._deadline = time.monotonic() + 600
                self._phase = 'pending'
                self._error = None
            return self._pending_state()

    def _pending_state(self):
        return {'phase': 'pending', 'user_code': self._code, 'verification_url': VERIFICATION_URL, 'plan': None, 'error': None}

    def _cancel(self):
        login_id = self._login_id
        with self._lock:
            self._login_id = self._code = self._deadline = None
            self._phase = 'disconnected'
        if login_id:
            self.transport.request('account/login/cancel', {'loginId': login_id})

    def cancel(self):
        with self._operation:
            self._cancel()
        return self.status()

    def logout(self):
        with self._operation:
            self._cancel()
            self.transport.request('account/logout')
            self._models_cache = None
            self._models_cache_at = 0.0
            self._phase = 'disconnected'
        return self.status()

    def open_verification(self):
        if not self._code:
            raise RuntimeError('먼저 연결을 시작해 주세요.')
        if not webbrowser.open(VERIFICATION_URL):
            raise RuntimeError('브라우저를 열지 못했습니다. 표시된 인증 주소를 직접 열어 주세요.')
        return {'opened': True}

    def models(self):
        if self.status()['phase'] != 'connected':
            raise RuntimeError('먼저 ChatGPT 계정을 연결해 주세요.')
        # Model metadata is account-scoped and changes infrequently. A GPT
        # review can contain dozens of windows; querying model/list for every
        # window adds avoidable transport latency and rate-limit pressure.
        now = time.monotonic()
        if self._models_cache is not None and now - self._models_cache_at < 30:
            return list(self._models_cache)
        models = []
        cursor = None
        for _ in range(20):
            params = {'limit': 100, 'includeHidden': False}
            if cursor:
                params['cursor'] = cursor
            result = self.transport.request('model/list', params)
            models.extend({'id': row.get('model', row['id']), 'name': row.get('displayName', row['id']),
                           'default_effort': row.get('defaultReasoningEffort'),
                           'efforts': [{'value': option['reasoningEffort'], 'description': option.get('description', '')}
                                       for option in row.get('supportedReasoningEfforts', [])]}
                          for row in result.get('data', []) if not row.get('hidden'))
            cursor = result.get('nextCursor')
            if not cursor:
                self._models_cache = list(models)
                self._models_cache_at = time.monotonic()
                return models
        raise RuntimeError('모델 목록을 모두 불러오지 못했습니다.')

    def check(self, model: str, effort: str | None = None):
        return self.complete(model, CHECK_PROMPT, effort=effort)

    def complete(self, model: str, prompt: str, effort: str | None = None,
                 output_schema: dict | None = None, cancelled=None, on_stage=None):
        report = on_stage or (lambda stage: None)
        report('models')
        # A long review can contain many windows. Re-querying account/read and
        # model/list for every window adds avoidable app-server latency and can
        # make an otherwise healthy connection look stalled. Reuse the short
        # lived model cache when available; models() still refreshes it when
        # the cache is cold or expired.
        now = time.monotonic()
        if self._models_cache is not None and now - self._models_cache_at < 30:
            available_models = list(self._models_cache)
        else:
            available_models = self.models()
        selected = next((row for row in available_models if row['id'] == model), None)
        if selected is None:
            names = ', '.join(str(row.get('name') or row['id']) for row in available_models[:8])
            suffix = f' 사용 가능: {names}' if names else ' 계정에서 사용할 수 있는 모델이 없습니다.'
            raise RuntimeError(f'선택한 모델을 사용할 수 없습니다.{suffix}')
        if effort is not None and effort not in {option['value'] for option in selected['efforts']}:
            raise RuntimeError('선택한 모델에서 지원하는 추론 강도를 선택해 주세요.')
        if not self._operation.acquire(blocking=False):
            raise RuntimeError('다른 연결 작업이 진행 중입니다.')
        thread_id = turn_id = None
        turn_finished = False
        events = queue.Queue()
        try:
            self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            workspace = self.home / 'connection-check'
            workspace.mkdir(exist_ok=True)
            self._events = events
            report('thread')
            thread = self.transport.request('thread/start', {
                'model': model, 'cwd': str(workspace), 'sandbox': 'read-only',
                'approvalPolicy': 'never', 'ephemeral': True,
                'baseInstructions': 'Analyze only the supplied fictional text. Do not use tools, execute commands, or inspect files.',
                'config': {'model_provider': 'openai', 'web_search': 'disabled', 'features.shell_tool': False},
            })
            thread_id = thread['thread']['id']
            turn_params = {'threadId': thread_id, 'input': [{'type': 'text', 'text': prompt}]}
            if effort is not None:
                turn_params['effort'] = effort
            if output_schema is not None:
                turn_params['outputSchema'] = output_schema
            report('start')
            # Turn creation can briefly queue behind the provider. Keep this
            # longer than the review response deadline so a slow handshake is
            # not mistaken for a failed request and retried unnecessarily.
            turn = self.transport.request('turn/start', turn_params, timeout=60)
            turn_id = turn['turn']['id']
            # Allow the selected reasoning level enough time to finish a
            # grounded Korean review. The caller still has a bounded window
            # and can split it, but a 45s hard cut caused normal provider
            # queueing to be reported as a failed segment.
            timeout_by_effort = {'low': 60, 'medium': 90, 'high': 120, 'xhigh': 150}
            deadline = time.monotonic() + timeout_by_effort.get(effort or 'medium', 90)
            report('wait')
            messages = []
            last_error = None
            while time.monotonic() < deadline:
                if cancelled and cancelled():
                    raise RuntimeError('GPT 분석이 취소되었습니다.')
                try:
                    method, params = events.get(timeout=min(1.0, max(.01, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if params.get('threadId') != thread_id:
                    continue
                if method == 'error':
                    if params.get('turnId') != turn_id:
                        continue
                    # The app-server emits informational retry events while
                    # its provider stream is offline. Waiting for all of its
                    # internal reconnect attempts can consume the whole
                    # review deadline; surface this as a bounded retryable
                    # provider error so the analyzer can isolate/retry the
                    # window promptly.
                    error_payload = params.get('error') or {}
                    error_message = str(error_payload.get('message', '')).lower() if isinstance(error_payload, dict) else ''
                    if 'reconnecting' in error_message or 'waiting for network' in error_message:
                        raise provider_error({'codexErrorInfo': {'httpConnectionFailed': {}}})
                    last_error = provider_error(params.get('error'))
                    if not params.get('willRetry'):
                        raise last_error
                    report('provider_retry')
                    continue
                if method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
                    messages.append(params['item'].get('text', ''))
                if method == 'turn/completed':
                    if params.get('turn', {}).get('id', turn_id) != turn_id:
                        continue
                    turn_finished = True
                    if params.get('turn', {}).get('status') != 'completed':
                        raise provider_error(params['turn']['error']) if params['turn'].get('error') else (last_error or provider_error(None))
                    text = (messages[-1] if output_schema and messages else '\n'.join(messages)).strip()
                    if not text:
                        raise RuntimeError('분석 응답이 비어 있습니다.')
                    return {'model': model, 'effort': effort, 'text': text}
            if last_error is not None:
                raise last_error
            raise RuntimeError(f'GPT 응답 대기 시간이 초과되었습니다 ({timeout_by_effort.get(effort or "medium", 90)}초).')
        finally:
            if thread_id and turn_id and not turn_finished:
                try:
                    self.transport.request('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id}, timeout=5)
                except RuntimeError:
                    pass
            self._events = None
            self._operation.release()
