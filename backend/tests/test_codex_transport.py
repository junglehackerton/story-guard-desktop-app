import subprocess
import sys
import pytest
from backend.app.services import codex_transport as module


def make_transport(tmp_path, monkeypatch):
    script = tmp_path / 'rpc.py'
    script.write_text('''import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 if m['method']=='hang': continue
 if m['method']=='die': break
 if m['method']=='error':
  print(json.dumps({'id':m['id'],'error':{'code':42,'message':'secret-token'}}),flush=True)
 else:
  print(json.dumps({'id':m['id'],'result':{'ok':True}}),flush=True)
''')
    original = subprocess.Popen
    monkeypatch.setattr(module, 'find_codex', lambda: sys.executable)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda command, **kwargs: original([sys.executable, '-u', str(script)], **kwargs))
    return module.CodexTransport(tmp_path / 'isolated')


def test_transport_handshake_error_redaction_and_close(tmp_path, monkeypatch):
    transport = make_transport(tmp_path, monkeypatch)
    try:
        assert transport.request('account/read') == {'ok': True}
        with pytest.raises(RuntimeError) as error:
            transport.request('error')
        assert 'secret-token' not in str(error.value)
    finally:
        process = transport._process
        transport.close()
    assert process.poll() is not None


def test_transport_timeout_and_process_exit(tmp_path, monkeypatch):
    transport = make_transport(tmp_path, monkeypatch)
    try:
        with pytest.raises(RuntimeError, match='초과'):
            transport.request('hang', timeout=.05)
        with pytest.raises(RuntimeError, match='process_exited'):
            transport.request('die', timeout=2)
        assert not transport._pending
    finally:
        transport.close()
