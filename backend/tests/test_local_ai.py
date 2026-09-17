import sys
from types import SimpleNamespace

from backend.app.services.local_ai import (
    DEFAULT_GENERATION_MODEL,
    DEFAULT_EMBEDDING_MODEL,
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
    (tmp_path / DEFAULT_EMBEDDING_MODEL).write_bytes(b"embedding")

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


def test_dedicated_embedding_model_and_query_instruction(monkeypatch):
    from backend.app.services.local_ai import DEFAULT_EMBEDDING_MODEL, LocalLlmEmbeddings
    assert DEFAULT_EMBEDDING_MODEL == "Qwen3-Embedding-0.6B-Q8_0.gguf"
    calls = []
    class Engine:
        def embed(self, text, **kwargs):
            calls.append((text, kwargs))
            return [1.0] * 1024
    embeddings = LocalLlmEmbeddings()
    monkeypatch.setattr(embeddings, "_llm", lambda: Engine())
    embeddings.embed_documents(["계약자만 검을 사용한다."])
    embeddings.embed_query("누가 검을 사용할 수 있나?")
    assert calls[0][0] == ["계약자만 검을 사용한다."]
    assert calls[1][0].startswith("Instruct: ")
    assert "\nQuery: 누가 검을 사용할 수 있나?" in calls[1][0]
    assert calls[1][1]["truncate"] is False


def test_embeddings_reject_token_matrix(monkeypatch):
    import pytest
    from backend.app.services.local_ai import LocalLlmEmbeddings
    embeddings = LocalLlmEmbeddings()
    monkeypatch.setattr(embeddings, "_llm", lambda: SimpleNamespace(embed=lambda *a, **k: [[1.0] * 1024] * 2))
    with pytest.raises(RuntimeError, match="벡터"):
        embeddings.embed_query("규칙")


def test_health_requires_embedding_as_well_as_generation(tmp_path):
    default_model_path(tmp_path).write_bytes(b'generator')
    assert not LocalAiRuntime(tmp_path).health().ok


def test_embedding_download_checks_integrity_and_preserves_existing_file(tmp_path, monkeypatch):
    import hashlib
    import pytest
    from backend.app.services import local_ai
    payload = b'validated-model'
    class Response:
        headers = {'content-length': str(len(payload))}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_bytes(self, **kwargs): yield payload
    monkeypatch.setattr(local_ai.httpx, 'stream', lambda *a, **k: Response())
    target = tmp_path / local_ai.DEFAULT_EMBEDDING_MODEL
    target.write_bytes(b'old-file')
    monkeypatch.setattr(local_ai, 'EMBEDDING_SHA256', 'bad-hash')
    with pytest.raises(RuntimeError, match='검증'):
        local_ai.download_embedding_model(tmp_path)
    assert target.read_bytes() == b'old-file'
    monkeypatch.setattr(local_ai, 'EMBEDDING_SHA256', hashlib.sha256(payload).hexdigest())
    assert local_ai.download_embedding_model(tmp_path).read_bytes() == payload
    monkeypatch.setattr(local_ai.httpx, 'stream', lambda *a, **k: pytest.fail('다운로드 재실행'))
    assert local_ai.download_embedding_model(tmp_path) == target


def test_embedding_context_failure_is_reported_as_recoverable_error(tmp_path, monkeypatch):
    import pytest
    from backend.app import services
    from backend.app.services import local_ai
    model = tmp_path / local_ai.DEFAULT_EMBEDDING_MODEL
    model.write_bytes(b"model")
    class BrokenLlama:
        def __init__(self, **kwargs):
            raise ValueError("native context unavailable")
    fake = SimpleNamespace(Llama=BrokenLlama, LLAMA_POOLING_TYPE_LAST=3)
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    local_ai.llama_cpp_available.cache_clear()
    local_ai.llama_supports_gpu_offload.cache_clear()
    embeddings = local_ai.LocalLlmEmbeddings(model_dir=tmp_path)
    with pytest.raises(RuntimeError, match="초기화하지 못했습니다"):
        embeddings.embed_query("규칙")
    local_ai.llama_cpp_available.cache_clear()
    local_ai.llama_supports_gpu_offload.cache_clear()


def test_embedding_retries_cpu_when_gpu_context_fails(tmp_path, monkeypatch):
    import pytest
    from backend.app.services import local_ai

    model = tmp_path / local_ai.DEFAULT_EMBEDDING_MODEL
    model.write_bytes(b"model")
    calls = []

    class RecoveringLlama:
        def __init__(self, **kwargs):
            calls.append(kwargs["n_gpu_layers"])
            if kwargs["n_gpu_layers"] != 0:
                raise ValueError("Metal queue unavailable")

        def embed(self, text, **kwargs):
            return [1.0] * 1024

    fake = SimpleNamespace(Llama=RecoveringLlama, LLAMA_POOLING_TYPE_LAST=3,
                           llama_supports_gpu_offload=lambda: True)
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    local_ai.llama_cpp_available.cache_clear()
    local_ai.llama_supports_gpu_offload.cache_clear()
    local_ai.LocalLlmEmbeddings._llm_cache.clear()
    embeddings = local_ai.LocalLlmEmbeddings(model_dir=tmp_path)

    assert len(embeddings.embed_query("규칙")) == 1024
    assert calls == [-1, 0]
    local_ai.LocalLlmEmbeddings._llm_cache.clear()
    local_ai.llama_cpp_available.cache_clear()
    local_ai.llama_supports_gpu_offload.cache_clear()


def test_embedding_context_defaults_to_laptop_safe_size(tmp_path, monkeypatch):
    from backend.app.services import local_ai

    model_path = tmp_path / DEFAULT_EMBEDDING_MODEL
    model_path.write_bytes(b"embedding")
    calls = []

    class FakeLlama:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed(self, *_args, **_kwargs):
            return [0.1] * 1024

    monkeypatch.setattr(local_ai, "llama_gpu_layer_count", lambda: 0)
    monkeypatch.delenv("GGML_METAL_DEVICES", raising=False)
    monkeypatch.setattr(local_ai, "llama_cpp_available", lambda: True)
    monkeypatch.setitem(sys.modules, "llama_cpp", SimpleNamespace(Llama=FakeLlama, LLAMA_POOLING_TYPE_LAST=1))
    local_ai.LocalLlmEmbeddings._llm_cache.clear()
    local_ai.LocalLlmEmbeddings(model_dir=tmp_path).embed_query("규칙")

    assert calls[0]["n_ctx"] == 512
    assert calls[0]["n_batch"] == 512
    assert calls[0]["n_threads"] == 4
    assert calls[0]["n_threads_batch"] == 4
    assert __import__("os").environ["GGML_METAL_DEVICES"] == "0"
    local_ai.LocalLlmEmbeddings._llm_cache.clear()


def test_embedding_query_is_compacted_for_512_token_context(tmp_path, monkeypatch):
    from backend.app.services import local_ai

    model_path = tmp_path / DEFAULT_EMBEDDING_MODEL
    model_path.write_bytes(b"embedding")
    seen = []

    class CompactingLlama:
        def __init__(self, **kwargs):
            pass

        def embed(self, text, **kwargs):
            seen.append(text)
            return [1.0] * 1024

    fake = SimpleNamespace(Llama=CompactingLlama, LLAMA_POOLING_TYPE_LAST=3)
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    local_ai.llama_cpp_available.cache_clear()
    local_ai.LocalLlmEmbeddings._llm_cache.clear()
    embeddings = local_ai.LocalLlmEmbeddings(model_dir=tmp_path)

    embeddings.embed_query("가나다라마바사" * 100)

    assert len(seen[0].split("Query: ", 1)[1]) <= local_ai.DEFAULT_QUERY_CHARS + 3
    local_ai.LocalLlmEmbeddings._llm_cache.clear()
    local_ai.llama_cpp_available.cache_clear()


def test_embedding_documents_are_batched_for_long_manuscripts(monkeypatch):
    from backend.app.services import local_ai

    calls = []

    class BatchLlama:
        def embed(self, values, **_kwargs):
            calls.append(values)
            return [[0.1] * 1024 for _ in values]

    embeddings = local_ai.LocalLlmEmbeddings()
    monkeypatch.setattr(embeddings, "_llm", lambda: BatchLlama())
    result = embeddings.embed_documents([f"청크 {index}" for index in range(33)])

    assert len(result) == 33
    assert [len(batch) for batch in calls] == [4, 4, 4, 4, 4, 4, 4, 4, 1]


def test_embedding_batch_override_is_capped(monkeypatch):
    from backend.app.services import local_ai
    calls = []
    class BatchLlama:
        def embed(self, values, **_kwargs):
            calls.append(values)
            return [[0.1] * 1024 for _ in values]
    embeddings = local_ai.LocalLlmEmbeddings()
    monkeypatch.setattr(embeddings, "_llm", lambda: BatchLlama())
    monkeypatch.setenv("STORY_GUARD_EMBED_BATCH", "99")
    embeddings.embed_documents([f"청크 {index}" for index in range(17)])
    assert [len(batch) for batch in calls] == [8, 8, 1]
