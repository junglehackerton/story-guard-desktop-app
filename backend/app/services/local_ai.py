from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
import os
import hashlib
import importlib.util
import math
import sys
import threading
from pathlib import Path

import httpx

from backend.app.config import models_path
from backend.app.models import LocalAiHealth


DEFAULT_MODEL_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
DEFAULT_GENERATION_MODEL = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEFAULT_EMBEDDING_MODEL = "Qwen3-Embedding-0.6B-Q8_0.gguf"
EMBEDDING_REVISION = "370f27d"
EMBEDDING_SHA256 = "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439"
EMBEDDING_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/"
    f"{EMBEDDING_REVISION}/{DEFAULT_EMBEDDING_MODEL}"
)
QUERY_INSTRUCTION = "Given a story consistency question, retrieve relevant passages from the manuscript."
# Qwen3-Embedding's packaged llama.cpp context defaults to 512 tokens. Korean
# characters can consume more than one token, so a whole multi-chunk retrieval
# prompt can overflow before the model returns a vector. Dense retrieval only
# needs a compact semantic hint; canonical lexical retrieval still receives
# the complete query in RagService.
DEFAULT_QUERY_CHARS = 220
DEFAULT_MODEL_URL = (
    "https://huggingface.co/"
    f"{DEFAULT_MODEL_REPO}/resolve/main/{DEFAULT_GENERATION_MODEL}"
)
MODEL_EXTENSIONS = {".gguf"}


def local_models_dir() -> Path:
    path = models_path()
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_local_models(model_dir: Path | None = None) -> list[str]:
    directory = model_dir or local_models_dir()
    if not directory.exists():
        return []
    return sorted(
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS
    )


def resolve_model_path(model: str, model_dir: Path | None = None) -> Path | None:
    model = model.strip()
    if not model:
        return None
    directory = model_dir or local_models_dir()
    direct = Path(model).expanduser()
    if direct.is_file() and direct.stat().st_size > 0:
        return direct.resolve()
    local = directory / model
    if local.is_file() and local.stat().st_size > 0:
        return local.resolve()
    return None


def default_model_path(model_dir: Path | None = None) -> Path:
    return (model_dir or local_models_dir()) / DEFAULT_GENERATION_MODEL


@lru_cache(maxsize=1)
def llama_cpp_available() -> bool:
    # Startup/status checks must not import the packaged llama.cpp extension;
    # that import can take minutes on macOS and blocks the welcome screen.
    # The actual embedding/generation path still imports it lazily and reports
    # a precise initialization error if the extension cannot load.
    if "llama_cpp" in sys.modules:
        return sys.modules["llama_cpp"] is not None
    return importlib.util.find_spec("llama_cpp") is not None


@lru_cache(maxsize=1)
def llama_supports_gpu_offload() -> bool:
    try:
        import llama_cpp
    except Exception:
        return False
    support_check = getattr(llama_cpp, "llama_supports_gpu_offload", None)
    if support_check is None:
        return False
    try:
        return bool(support_check())
    except Exception:
        return False


def llama_gpu_layer_count() -> int:
    if not llama_supports_gpu_offload():
        return 0
    raw_value = os.getenv("STORY_GUARD_GPU_LAYERS", "-1").strip()
    try:
        return int(raw_value)
    except ValueError:
        return -1


def download_default_model(
    model_dir: Path | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> Path:
    directory = model_dir or local_models_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = default_model_path(directory)
    if target.is_file() and target.stat().st_size > 0:
        return target

    partial = target.with_suffix(f"{target.suffix}.part")
    downloaded = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={downloaded}-"} if downloaded > 0 else None
    with httpx.stream(
        "GET",
        DEFAULT_MODEL_URL,
        headers=headers,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=None),
    ) as response:
        if response.status_code == 416:
            partial.replace(target)
            return target
        response.raise_for_status()
        total_header = response.headers.get("content-length")
        total = int(total_header) + downloaded if total_header and total_header.isdigit() else None
        mode = "ab" if response.status_code == 206 and downloaded > 0 else "wb"
        if mode == "wb":
            downloaded = 0
        with partial.open(mode) as file:
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                file.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)

    partial.replace(target)
    return target


def download_embedding_model(model_dir: Path | None = None, progress=None) -> Path:
    directory = model_dir or local_models_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / DEFAULT_EMBEDDING_MODEL
    if target.is_file() and _sha256(target) == EMBEDDING_SHA256:
        return target
    partial = target.with_suffix(".gguf.part")
    with httpx.stream("GET", EMBEDDING_MODEL_URL, follow_redirects=True,
                      timeout=httpx.Timeout(30.0, read=None)) as response:
        response.raise_for_status()
        total = response.headers.get("content-length", "")
        total = int(total) if total.isdigit() else None
        downloaded = 0
        with partial.open("wb") as file:
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                file.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
    if _sha256(partial) != EMBEDDING_SHA256:
        raise RuntimeError("임베딩 모델 파일 검증에 실패했습니다. 다시 다운로드해 주세요.")
    partial.replace(target)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalAiRuntime:
    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = model_dir or local_models_dir()

    def health(self) -> LocalAiHealth:
        try:
            self.model_dir.mkdir(parents=True, exist_ok=True)
            models = list_local_models(self.model_dir)
        except OSError as error:
            return LocalAiHealth(
                ok=False,
                runtime="story-guard-local",
                message=f"로컬 모델 폴더를 준비하지 못했습니다: {error}",
                models=[],
                model_dir=str(self.model_dir),
            )

        runtime_ready = llama_cpp_available()
        model_ready = (resolve_model_path(DEFAULT_GENERATION_MODEL, self.model_dir) is not None
                       and resolve_model_path(DEFAULT_EMBEDDING_MODEL, self.model_dir) is not None)

        if runtime_ready and model_ready:
            return LocalAiHealth(
                ok=True,
                runtime="llama.cpp",
                message="앱 관리 로컬 모델 준비 완료",
                models=models,
                model_dir=str(self.model_dir),
            )

        return LocalAiHealth(
            ok=False,
            runtime="llama.cpp" if runtime_ready else "missing",
            message=(
                "로컬 모델 설치가 필요합니다. 임베딩·분석 모델 준비 상태를 확인해 주세요."
                if runtime_ready
                else "llama.cpp 런타임이 설치되어 있지 않습니다."
            ),
            models=models,
            model_dir=str(self.model_dir),
        )


class LocalLlmEmbeddings:
    """LangChain-compatible embeddings backed by the installed local GGUF model."""

    _llm_cache: dict[str, object] = {}
    _lock = threading.RLock()

    def __init__(self, model: str = DEFAULT_EMBEDDING_MODEL, model_dir: Path | None = None) -> None:
        self.model = model
        self.model_dir = model_dir

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # llama.cpp accepts a list of inputs and can reuse the loaded graph
        # across them. Keep batches small enough for laptop memory while
        # avoiding one native context call per chunk in a long manuscript.
        vectors: list[list[float]] = []
        with self._lock:
            llm = self._llm()
            # llama.cpp's embedding path saturates on small batches on
            # laptop CPUs; larger batches cause quadratic memory pressure.
            # Keep the measured default of 4, while allowing a bounded local
            # override for faster or more memory-constrained machines.
            try:
                requested_batch = int(os.getenv("STORY_GUARD_EMBED_BATCH", "4"))
            except ValueError:
                requested_batch = 4
            batch_size = max(1, min(requested_batch, 8))
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                raw = llm.embed(batch, normalize=True, truncate=False)
                if raw and isinstance(raw[0], (int, float)):
                    raw = [raw]
                vectors.extend(self._validate_vectors(raw))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed(f"Instruct: {QUERY_INSTRUCTION}\nQuery: {self._compact_query(text)}")

    @staticmethod
    def _compact_query(text: str) -> str:
        try:
            limit = int(os.getenv("STORY_GUARD_EMBED_QUERY_CHARS", str(DEFAULT_QUERY_CHARS)))
        except ValueError:
            limit = DEFAULT_QUERY_CHARS
        limit = max(80, min(limit, 480))
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        # Keep both the current window lead and the final question/claims;
        # this is more useful than a hard prefix cut for cross-chapter checks.
        head = max(1, int(limit * 0.65))
        return value[:head].rstrip() + "\n…\n" + value[-(limit - head - 3):].lstrip()

    def _embed(self, text: str) -> list[float]:
        with self._lock:
            vector = self._llm().embed(text, normalize=True, truncate=False)
        return self._validate_vectors([vector])[0]

    @staticmethod
    def _validate_vectors(values) -> list[list[float]]:
        if not values or any(
            not isinstance(vector, list)
            or len(vector) != 1024
            or not all(math.isfinite(value) for value in vector)
            for vector in values
        ):
            raise RuntimeError("임베딩 모델이 올바른 1,024차원 문장 벡터를 반환하지 않았습니다.")
        return [[float(value) for value in vector] for vector in values]

    def identity(self) -> str:
        path = resolve_model_path(self.model, self.model_dir)
        stamp = f"{path}:{path.stat().st_size}:{path.stat().st_mtime_ns}" if path else self.model
        # Bump the namespace when the persisted vector format/chunk policy
        # changes. This leaves older Chroma data untouched and avoids trying
        # to decompress an index created by an incompatible runtime.
        return hashlib.sha256(f"qwen3-last-normalized-v2:{QUERY_INSTRUCTION}:{stamp}".encode()).hexdigest()[:24]

    def _llm(self):
        model_path = resolve_model_path(self.model, self.model_dir)
        if model_path is None:
            raise RuntimeError("로컬 모델 설치가 필요합니다. 임베딩·분석 모델 준비 상태를 확인해 주세요.")
        cache_key = self.identity()
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]
        if not llama_cpp_available():
            raise RuntimeError("llama.cpp 런타임이 설치되어 있지 않습니다.")
        # llama.cpp's macOS wheel can expose Metal while reporting a null
        # default device in a packaged process. Pin the default selector to
        # the first device so CPU fallback and GPU offload use the same
        # reproducible backend; callers may still override it explicitly.
        os.environ.setdefault("GGML_METAL_DEVICES", "0")
        from llama_cpp import Llama, LLAMA_POOLING_TYPE_LAST

        gpu_layers = llama_gpu_layer_count()
        # Keep the default context conservative for laptops. Embedding only
        # needs to cover one chunk at a time; allocating the model's full
        # training context can exhaust unified memory before the first vector
        # is produced. Advanced users can raise this with an environment
        # override for larger chunks.
        try:
            requested_context = int(os.getenv("STORY_GUARD_EMBED_N_CTX", "512"))
        except ValueError:
            requested_context = 512
        context_size = max(256, min(requested_context, 4096))
        try:
            requested_threads = int(os.getenv("STORY_GUARD_EMBED_THREADS", "4"))
        except ValueError:
            requested_threads = 4
        options = {
            "model_path": str(model_path),
            "embedding": True,
            "pooling_type": LLAMA_POOLING_TYPE_LAST,
            # Embedding sequences must fit in a single batch without truncation.
            # The default 900-character splitter can produce roughly 600+
            # Korean tokens, so a 512-token batch intermittently fails on
            # ordinary chapters. Keep the batch bounded for laptop memory,
            # but never below the configured context window.
            "n_batch": min(2048, context_size),
            "n_ubatch": min(2048, context_size),
            "n_ctx": context_size,
            "n_threads": max(1, min(requested_threads, 8)),
            "n_threads_batch": max(1, min(requested_threads, 8)),
            "n_gpu_layers": gpu_layers,
            # CPU fallback must not ask llama.cpp to allocate a device-backed
            # K/Q/V cache. Some macOS builds report GPU support but cannot
            # create a Metal queue in a packaged or sandboxed process.
            "offload_kqv": gpu_layers != 0,
            "verbose": False,
        }
        try:
            llm = Llama(**options)
        except Exception as error:
            # A runtime can advertise GPU offload while the current machine or
            # sandbox cannot create its device queue. Retry on CPU before
            # presenting a hard failure; this keeps local-first indexing usable
            # on Macs without a working Metal context and on Windows CPU-only
            # machines.
            if gpu_layers == 0:
                raise RuntimeError(
                    "임베딩 모델을 초기화하지 못했습니다(CPU/Metal 백엔드). 앱을 다시 시작하거나 "
                    "CPU 전용 llama.cpp 실행 파일을 사용해 주세요."
                ) from error
            options["n_gpu_layers"] = 0
            options["offload_kqv"] = False
            try:
                llm = Llama(**options)
            except Exception as cpu_error:
                raise RuntimeError(
                    "임베딩 모델을 초기화하지 못했습니다(CPU/Metal 백엔드). 앱을 다시 시작하거나 "
                    "CPU 전용 llama.cpp 실행 파일을 사용해 주세요."
                ) from cpu_error
        self._llm_cache[cache_key] = llm
        return llm
