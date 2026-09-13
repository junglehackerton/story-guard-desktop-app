from backend.app.models import AppSettings
from backend.app.services import environment_setup as setup
from backend.app.services.local_ai import DEFAULT_EMBEDDING_MODEL, DEFAULT_GENERATION_MODEL


def test_embedding_readiness_is_independent_of_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "local_models_dir", lambda: tmp_path)
    monkeypatch.setattr(setup, "llama_cpp_available", lambda: True)
    (tmp_path / DEFAULT_GENERATION_MODEL).write_bytes(b"model")
    manager = setup.EnvironmentSetupManager(lambda *a: None, AppSettings)
    assert manager.status().generation_model_ready
    assert not manager.status().embedding_model_ready
    assert not manager.status().ready
    (tmp_path / DEFAULT_EMBEDDING_MODEL).write_bytes(b"embedding")
    assert manager.status().ready


def test_embedding_only_setup_does_not_download_generation(tmp_path, monkeypatch):
    from backend.app.models import EnvironmentSetupRequest
    monkeypatch.setattr(setup, "models_path", lambda: tmp_path)
    monkeypatch.setattr(setup, "llama_cpp_available", lambda: True)
    calls = []
    monkeypatch.setattr(setup, "download_embedding_model", lambda *a, **k: calls.append('embedding'))
    monkeypatch.setattr(setup, "download_default_model", lambda *a, **k: calls.append('generation'))
    manager = setup.EnvironmentSetupManager(lambda *a: None, AppSettings)
    manager._run(EnvironmentSetupRequest(prepare_generation_model=False))
    assert manager.progress().stage == 'complete'
    assert calls == ['embedding']

def test_gemma_selection_is_preserved_without_downloading_qwen(tmp_path, monkeypatch):
    from backend.app.models import EnvironmentSetupRequest
    monkeypatch.setattr(setup,'models_path',lambda:tmp_path)
    monkeypatch.setattr(setup,'llama_cpp_available',lambda:True)
    calls=[]
    monkeypatch.setattr(setup,'download_gemma',lambda path:calls.append('gemma'))
    monkeypatch.setattr(setup,'download_embedding_model',lambda *a,**k:calls.append('qwen'))
    saved=[]
    manager=setup.EnvironmentSetupManager(lambda *args:saved.append(args),AppSettings)
    manager._run(EnvironmentSetupRequest(embedding_model='embeddinggemma-300m',prepare_generation_model=False))
    assert calls==['gemma']
    assert saved[0][0]=='embeddinggemma-300m'
