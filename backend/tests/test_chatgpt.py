from pathlib import Path
import pytest
from backend.app.services.chatgpt import ChatGptConnection, isolated_environment


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.account = None
        self.callback = lambda *a: None
    def request(self, method, params=None, timeout=30):
        self.calls.append((method, params))
        if method == 'account/login/start':
            return {'loginId': 'login-1', 'verificationUrl': 'https://auth.openai.com/codex/device', 'userCode': 'ABCD-1234'}
        if method == 'account/read': return {'account': self.account}
        if method == 'model/list': return {'data': [{'id': 'model-a', 'model': 'model-a', 'displayName': 'Model A', 'defaultReasoningEffort': 'medium', 'supportedReasoningEfforts': [{'reasoningEffort': 'low', 'description': 'Fast'}, {'reasoningEffort': 'medium', 'description': 'Balanced'}, {'reasoningEffort': 'high', 'description': 'Thorough'}]}], 'nextCursor': None}
        return {}
    def close(self): pass


def test_device_login_state_and_completion(tmp_path):
    transport = FakeTransport()
    connection = ChatGptConnection(tmp_path, transport)
    state = connection.login()
    assert state['phase'] == 'pending'
    assert state['user_code'] == 'ABCD-1234'
    assert transport.calls[-1] == ('account/login/start', {'type': 'chatgptDeviceCode'})
    transport.account = {'type': 'chatgpt', 'planType': 'plus', 'email': 'writer@example.com'}
    connection.on_notification('account/login/completed', {'loginId': 'login-1', 'success': True})
    assert connection.status()['phase'] == 'connected'
    assert connection.status()['user_code'] is None
    assert all(params == {'refreshToken': False} for method, params in transport.calls if method == 'account/read')
    assert connection.models()[0]['id'] == 'model-a'
    assert connection.models()[0]['default_effort'] == 'medium'
    assert [x['value'] for x in connection.models()[0]['efforts']] == ['low', 'medium', 'high']


def test_models_are_cached_across_review_windows(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt', 'planType': 'plus'}
    connection = ChatGptConnection(tmp_path, transport)
    assert connection.models()[0]['id'] == 'model-a'
    assert connection.models()[0]['id'] == 'model-a'
    assert len([call for call in transport.calls if call[0] == 'model/list']) == 1
    connection.logout()
    # A subsequent account/session must not reuse the previous account's list.
    assert len([call for call in transport.calls if call[0] == 'model/list']) == 1


def test_api_key_auth_is_never_treated_as_subscription(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'apiKey'}
    connection = ChatGptConnection(tmp_path, transport)
    assert connection.status()['phase'] != 'connected'
    with pytest.raises(RuntimeError, match='ChatGPT'):
        connection.models()


def test_status_falls_back_to_local_token_when_refresh_is_offline(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt', 'planType': 'plus'}
    original = transport.request
    refresh_attempts = []

    def request(method, params=None, timeout=30):
        if method == 'account/read':
            refresh_attempts.append(params['refreshToken'])
            if params['refreshToken']:
                raise RuntimeError('네트워크 연결 실패')
        return original(method, params, timeout)

    transport.request = request
    connection = ChatGptConnection(tmp_path, transport)
    assert connection.status()['phase'] == 'connected'
    assert refresh_attempts == [False]


def test_cancel_and_late_notification_do_not_reconnect(tmp_path):
    transport = FakeTransport()
    connection = ChatGptConnection(tmp_path, transport)
    connection.login()
    connection.cancel()
    connection.on_notification('account/login/completed', {'loginId': 'login-1', 'success': True})
    assert connection.status()['phase'] == 'disconnected'
    assert any(method == 'account/login/cancel' for method, _ in transport.calls)


def test_environment_does_not_inherit_other_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'secret')
    monkeypatch.setenv('CODEX_ACCESS_TOKEN', 'secret')
    env = isolated_environment(tmp_path)
    assert 'OPENAI_API_KEY' not in env
    assert 'CODEX_ACCESS_TOKEN' not in env
    assert env['CODEX_HOME'] == str(tmp_path)


def test_untrusted_verification_url_is_rejected(tmp_path):
    transport = FakeTransport()
    transport.request = lambda *a, **k: {'loginId': 'x', 'verificationUrl': 'https://example.org/phishing', 'userCode': '123456'}
    with pytest.raises(RuntimeError, match='인증 주소'):
        ChatGptConnection(tmp_path, transport).login()


def test_check_uses_selected_model_and_fixed_sample(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt', 'planType': 'plus'}
    connection = ChatGptConnection(tmp_path, transport)
    original = transport.request
    def request(method, params=None, timeout=30):
        if method == 'thread/start':
            assert params['model'] == 'model-a'
            assert params['sandbox'] == 'read-only'
            assert params['ephemeral'] is True
            return {'thread': {'id': 'thread-1'}}
        if method == 'turn/start':
            assert '가상의 원고' in params['input'][0]['text']
            assert params['effort'] == 'high'
            transport.callback('item/completed', {'threadId': 'thread-1', 'item': {'type': 'agentMessage', 'text': '6화 계약으로 규칙 위반을 단정할 수 없습니다.'}})
            transport.callback('turn/completed', {'threadId': 'thread-1', 'turn': {'id': 'turn-1', 'status': 'completed'}})
            return {'turn': {'id': 'turn-1'}}
        return original(method, params, timeout)
    transport.request = request
    assert '6화' in connection.check('model-a', 'high')['text']
    with pytest.raises(RuntimeError, match='Model A'):
        connection.check('unavailable-model')


def test_request_stages_are_reported_before_transport_calls(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt'}
    connection = ChatGptConnection(tmp_path, transport)
    stages = []
    original = transport.request
    def request(method, params=None, timeout=30):
        if method == 'thread/start':
            assert stages[-1] == 'thread'
            return {'thread': {'id': 't'}}
        if method == 'turn/start':
            assert stages[-1] == 'start'
            transport.callback('item/completed', {'threadId': 't', 'item': {'type': 'agentMessage', 'text': '{}'}})
            transport.callback('turn/completed', {'threadId': 't', 'turn': {'status': 'completed'}})
            return {'turn': {'id': 'u'}}
        return original(method, params, timeout)
    transport.request = request
    connection.complete('model-a', '원고', effort='medium', on_stage=stages.append)
    assert stages == ['models', 'thread', 'start', 'wait']


def test_provider_reconnecting_event_is_surface_as_retryable_error(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt'}
    connection = ChatGptConnection(tmp_path, transport)
    original = transport.request
    def request(method, params=None, timeout=30):
        if method == 'thread/start':
            return {'thread': {'id': 't'}}
        if method == 'turn/start':
            transport.callback('error', {'threadId': 't', 'turnId': 'u', 'willRetry': True,
                'error': {'message': 'Reconnecting... waiting for network'}})
            return {'turn': {'id': 'u'}}
        return original(method, params, timeout)
    transport.request = request
    with pytest.raises(Exception) as raised:
        connection.complete('model-a', '원고', effort='low')
    assert getattr(raised.value, 'code', None) == 'provider_unavailable'
    assert getattr(raised.value, 'retryable', False) is True


def test_login_failure_clears_device_code(tmp_path):
    transport = FakeTransport()
    connection = ChatGptConnection(tmp_path, transport)
    connection.login()
    connection.on_notification('account/login/completed', {'loginId': 'login-1', 'success': False})
    state = connection.status()
    assert state['phase'] == 'failed'
    assert state['user_code'] is None


def test_unsupported_effort_is_rejected_before_turn(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt'}
    connection = ChatGptConnection(tmp_path, transport)
    with pytest.raises(RuntimeError, match='추론'):
        connection.check('model-a', 'ultra')
    assert not any(method == 'thread/start' for method, _ in transport.calls)


@pytest.mark.parametrize('info,code,retryable,stop_run', [
    ('usageLimitExceeded', 'usage_limit', False, True),
    ('unauthorized', 'authentication', False, True),
    ('rateLimitExceeded', 'rate_limit', True, False),
    ('contextWindowExceeded', 'context_length', False, False),
    ({'httpConnectionFailed': {'httpStatusCode': 401}}, 'authentication', False, True),
    ({'httpConnectionFailed': {'httpStatusCode': 503}}, 'provider_unavailable', True, False),
    ('other', 'unknown_provider_error', False, False),
])
def test_provider_failure_preserves_safe_category(tmp_path, info, code, retryable, stop_run):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt'}
    connection = ChatGptConnection(tmp_path, transport)
    original = transport.request
    def request(method, params=None, timeout=30):
        if method == 'thread/start':
            return {'thread': {'id': 't'}}
        if method == 'turn/start':
            transport.callback('turn/completed', {'threadId': 't', 'turn': {'id': 'u', 'status': 'failed',
                'error': {'codexErrorInfo': info, 'message': 'secret-token and manuscript content'}}})
            return {'turn': {'id': 'u'}}
        return original(method, params, timeout)
    transport.request = request
    with pytest.raises(RuntimeError) as error:
        connection.complete('model-a', '원고', effort='medium')
    assert getattr(error.value, 'code', None) == code
    assert error.value.retryable is retryable
    assert error.value.stop_run is stop_run
    assert 'secret-token' not in str(error.value)
    assert 'manuscript content' not in str(error.value)


def test_final_error_notification_is_not_lost_when_turn_has_no_error(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt'}
    connection = ChatGptConnection(tmp_path, transport)
    original = transport.request
    def request(method, params=None, timeout=30):
        if method == 'thread/start': return {'thread': {'id': 't'}}
        if method == 'turn/start':
            transport.callback('error', {'threadId': 't', 'turnId': 'u', 'willRetry': False,
                'error': {'codexErrorInfo': 'usageLimitExceeded', 'message': 'private'}})
            transport.callback('turn/completed', {'threadId': 't', 'turn': {'id': 'u', 'status': 'failed'}})
            return {'turn': {'id': 'u'}}
        return original(method, params, timeout)
    transport.request = request
    with pytest.raises(RuntimeError) as error:
        connection.complete('model-a', '원고', effort='medium')
    assert getattr(error.value, 'code', None) == 'usage_limit'


def test_provider_retry_can_recover_without_interrupting_completed_turn(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt'}
    connection = ChatGptConnection(tmp_path, transport)
    original = transport.request
    stages, methods = [], []
    def request(method, params=None, timeout=30):
        methods.append(method)
        if method == 'thread/start': return {'thread': {'id': 't'}}
        if method == 'turn/start':
            transport.callback('error', {'threadId': 't', 'turnId': 'u', 'willRetry': True,
                'error': {'codexErrorInfo': 'serverOverloaded', 'message': 'private'}})
            transport.callback('item/completed', {'threadId': 't', 'item': {'type': 'agentMessage', 'text': '{}'}})
            transport.callback('turn/completed', {'threadId': 't', 'turn': {'id': 'u', 'status': 'completed'}})
            return {'turn': {'id': 'u'}}
        return original(method, params, timeout)
    transport.request = request
    assert connection.complete('model-a', '원고', effort='medium', on_stage=stages.append)['text'] == '{}'
    assert 'provider_retry' in stages
    assert 'turn/interrupt' not in methods


def test_final_provider_error_interrupts_unfinished_turn(tmp_path):
    transport = FakeTransport()
    transport.account = {'type': 'chatgpt'}
    connection = ChatGptConnection(tmp_path, transport)
    original = transport.request
    methods = []
    def request(method, params=None, timeout=30):
        methods.append(method)
        if method == 'thread/start': return {'thread': {'id': 't'}}
        if method == 'turn/start':
            transport.callback('error', {'threadId': 't', 'turnId': 'u', 'willRetry': False,
                'error': {'codexErrorInfo': 'unauthorized', 'message': 'private'}})
            return {'turn': {'id': 'u'}}
        return original(method, params, timeout)
    transport.request = request
    with pytest.raises(RuntimeError, match='인증'):
        connection.complete('model-a', '원고', effort='medium')
    assert 'turn/interrupt' in methods
    assert not connection._operation.locked()
