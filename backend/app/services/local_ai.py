from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
import os
from pathlib import Path

import httpx

from backend.app.config import models_path
from backend.app.models import LocalAiHealth


DEFAULT_MODEL_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
DEFAULT_GENERATION_MODEL = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEFAULT_EMBEDDING_MODEL = DEFAULT_GENERATION_MODEL
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
    if direct.is_file():
        return direct.resolve()
    local = directory / model
    if local.is_file():
        return local.resolve()
    return None


def default_model_path(model_dir: Path | None = None) -> Path:
    return (model_dir or local_models_dir()) / DEFAULT_GENERATION_MODEL


@lru_cache(maxsize=1)
def llama_cpp_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
    except Exception:
        return False
    return True


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
        model_ready = default_model_path(self.model_dir).is_file()

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
                "로컬 LLM 모델이 설치되어 있지 않습니다."
                if runtime_ready
                else "llama.cpp 런타임이 설치되어 있지 않습니다."
            ),
            models=models,
            model_dir=str(self.model_dir),
        )


class LocalLlmEmbeddings:
    """LangChain-compatible embeddings backed by the installed local GGUF model."""

    _llm_cache: dict[str, object] = {}

    def __init__(self, model: str = DEFAULT_EMBEDDING_MODEL, model_dir: Path | None = None) -> None:
        self.model = model
        self.model_dir = model_dir

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = self._llm().embed(text, normalize=True)
        if vector and isinstance(vector[0], list):
            return [float(value) for value in vector[0]]
        return [float(value) for value in vector]

    def _llm(self):
        model_path = resolve_model_path(self.model, self.model_dir)
        if model_path is None:
            raise RuntimeError("로컬 LLM 모델이 설치되어 있지 않습니다.")
        cache_key = str(model_path)
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]
        if not llama_cpp_available():
            raise RuntimeError("llama.cpp 런타임이 설치되어 있지 않습니다.")
        from llama_cpp import Llama

        llm = Llama(
            model_path=cache_key,
            embedding=True,
            n_ctx=2048,
            n_threads=4,
            n_gpu_layers=llama_gpu_layer_count(),
            verbose=False,
        )
        self._llm_cache[cache_key] = llm
        return llm
