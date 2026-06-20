from backend.app.services.local_ai import (
    DEFAULT_GENERATION_MODEL,
    LocalAiRuntime,
    default_model_path,
    list_local_models,
    resolve_model_path,
)


def test_local_models_are_discovered_from_model_dir(tmp_path) -> None:
    model = tmp_path / DEFAULT_GENERATION_MODEL
    model.write_bytes(b"placeholder")

    assert list_local_models(tmp_path) == [DEFAULT_GENERATION_MODEL]
    assert resolve_model_path(DEFAULT_GENERATION_MODEL, tmp_path) == model.resolve()
    assert default_model_path(tmp_path) == model


def test_local_ai_runtime_requires_default_model_file(tmp_path) -> None:
    health = LocalAiRuntime(tmp_path).health()

    assert health.ok is False
    assert health.model_dir == str(tmp_path)


def test_local_ai_runtime_is_ready_with_default_model_file(tmp_path) -> None:
    default_model_path(tmp_path).write_bytes(b"placeholder")

    health = LocalAiRuntime(tmp_path).health()

    assert health.ok is True
    assert health.runtime == "llama.cpp"
