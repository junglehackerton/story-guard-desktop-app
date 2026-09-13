from __future__ import annotations

import platform
import threading
from collections.abc import Callable

from backend.app.services.embedding_models import GEMMA_MODEL, gemma_ready, download_gemma
from backend.app.config import models_path
from backend.app.models import (
    AppSettings,
    EnvironmentSetupProgress,
    EnvironmentSetupRequest,
    EnvironmentStatus,
)
from backend.app.services.local_ai import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_MODEL_REPO,
    download_default_model,
    download_embedding_model,
    llama_cpp_available,
    list_local_models,
    local_models_dir,
    resolve_model_path,
)


SaveSettings = Callable[[str, str], None]
LoadSettings = Callable[[], AppSettings]


class EnvironmentSetupManager:
    def __init__(self, save_settings: SaveSettings, load_settings: LoadSettings) -> None:
        self._save_settings = save_settings
        self._load_settings = load_settings
        self._lock = threading.Lock()
        self._progress = EnvironmentSetupProgress(
            running=False,
            stage="idle",
            message="로컬 AI 환경을 확인하지 않았습니다.",
            logs=[],
        )

    def status(self) -> EnvironmentStatus:
        model_dir = local_models_dir()
        models = list_local_models(model_dir)
        settings = self._load_settings()
        embedding_model = settings.embedding_model or DEFAULT_EMBEDDING_MODEL
        generation_model = settings.generation_model.strip() or DEFAULT_GENERATION_MODEL
        runtime_ready = llama_cpp_available()
        generation_ready = runtime_ready and resolve_model_path(generation_model, model_dir) is not None

        embedding_ready = (gemma_ready(model_dir) if embedding_model == GEMMA_MODEL else runtime_ready and resolve_model_path(embedding_model, model_dir) is not None)

        return EnvironmentStatus(
            platform=platform.system().lower() or "unknown",
            runtime_installed=runtime_ready,
            runtime_running=runtime_ready,
            model_dir=str(model_dir),
            embedding_model=embedding_model,
            generation_model=generation_model,
            embedding_model_ready=embedding_ready,
            generation_model_ready=generation_ready,
            models=models,
            ready=generation_ready and embedding_ready,
            can_auto_install=True,
            install_method=f"download {DEFAULT_MODEL_REPO}",
            message=("임베딩 모델 설치가 필요합니다." if runtime_ready and not embedding_ready
                     else environment_message(runtime_ready, generation_model, generation_ready, models)),
        )

    def progress(self) -> EnvironmentSetupProgress:
        with self._lock:
            return self._progress.model_copy(deep=True)

    def start(self, request: EnvironmentSetupRequest) -> EnvironmentSetupProgress:
        with self._lock:
            if self._progress.running:
                return self._progress.model_copy(deep=True)
            self._progress = EnvironmentSetupProgress(
                running=True,
                stage="start",
                message="로컬 AI 모델 폴더를 준비합니다.",
                logs=[],
            )
        thread = threading.Thread(target=self._run, args=(request,), daemon=True)
        thread.start()
        return self.progress()

    def _run(self, request: EnvironmentSetupRequest) -> None:
        try:
            self._log("models", "앱 관리 LLM 모델 폴더를 확인합니다.")
            model_dir = models_path()
            model_dir.mkdir(parents=True, exist_ok=True)

            embedding_model = request.embedding_model or DEFAULT_EMBEDDING_MODEL
            if embedding_model not in {DEFAULT_EMBEDDING_MODEL, GEMMA_MODEL}:
                raise ValueError("지원하지 않는 임베딩 모델입니다.")
            if not llama_cpp_available() and (request.prepare_generation_model or embedding_model != GEMMA_MODEL):
                raise RuntimeError("llama.cpp 런타임이 설치되어 있지 않습니다.")

            last_bucket = -1

            def report(downloaded: int, total: int | None) -> None:
                nonlocal last_bucket
                bucket = downloaded // (25 * 1024 * 1024)
                if bucket != last_bucket:
                    last_bucket = bucket
                    message = f"{downloaded / total * 100:.1f}%" if total else f"{downloaded // (1024 * 1024)} MB"
                    self._log("download", f"모델 다운로드 중: {message}")

            if request.prepare_embedding_model:
                self._log("download", f"전용 임베딩 모델을 준비합니다: {embedding_model}")
                if embedding_model == GEMMA_MODEL:
                    download_gemma(model_dir)
                else:
                    download_embedding_model(model_dir, progress=report)
                self._log("download", "임베딩 모델 파일 검증 완료")

            generation_model = (request.generation_model or DEFAULT_GENERATION_MODEL).strip()
            if request.prepare_generation_model:
                if generation_model == DEFAULT_GENERATION_MODEL:
                    last_bucket = -1
                    self._log("download", f"로컬 분석 모델을 준비합니다: {generation_model}")
                    download_default_model(model_dir, progress=report)
                elif resolve_model_path(generation_model, model_dir) is None:
                    raise RuntimeError(f"'{generation_model}' 모델 파일을 찾지 못했습니다.")

            self._save_settings(embedding_model, generation_model)
            self._complete("선택한 로컬 모델 준비 완료")

        except Exception as error:
            self._fail(str(error))

    def _log(self, stage: str, message: str) -> None:
        with self._lock:
            logs = [*self._progress.logs, message]
            self._progress = EnvironmentSetupProgress(
                running=True,
                stage=stage,
                message=message,
                logs=logs,
            )

    def _complete(self, message: str) -> None:
        with self._lock:
            self._progress = EnvironmentSetupProgress(
                running=False,
                stage="complete",
                message=message,
                logs=[*self._progress.logs, message],
            )

    def _fail(self, message: str) -> None:
        with self._lock:
            self._progress = EnvironmentSetupProgress(
                running=False,
                stage="failed",
                message="로컬 AI 환경 준비 실패",
                logs=self._progress.logs,
                error=message,
            )


def environment_message(
    runtime_ready: bool,
    generation_model: str,
    generation_ready: bool,
    models: list[str],
) -> str:
    if not runtime_ready:
        return "llama.cpp 런타임이 설치되어 있지 않습니다."
    if not generation_ready:
        return "로컬 LLM 모델 설치가 필요합니다."
    if models:
        return "로컬 LLM 모델 준비 완료"
    return f"로컬 LLM 모델 설치가 필요합니다: {generation_model}"
