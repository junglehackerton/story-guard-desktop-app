import sys
from types import SimpleNamespace

from backend.app.services.local_ai import (
    DEFAULT_GENERATION_MODEL,
    LocalAiRuntime,
    default_model_path,
    llama_gpu_layer_count,
    llama_supports_gpu_offload,
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


def test_llama_gpu_layer_count_uses_all_layers_when_offload_is_supported(monkeypatch) -> None:
    llama_supports_gpu_offload.cache_clear()
    monkeypatch.delenv("STORY_GUARD_GPU_LAYERS", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "llama_cpp",
        SimpleNamespace(llama_supports_gpu_offload=lambda: True),
    )

    assert llama_gpu_layer_count() == -1


def test_llama_gpu_layer_count_disables_gpu_when_runtime_does_not_support_it(monkeypatch) -> None:
    llama_supports_gpu_offload.cache_clear()
    monkeypatch.delenv("STORY_GUARD_GPU_LAYERS", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "llama_cpp",
        SimpleNamespace(llama_supports_gpu_offload=lambda: False),
    )

    assert llama_gpu_layer_count() == 0
