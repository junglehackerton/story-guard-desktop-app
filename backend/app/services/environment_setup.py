from __future__ import annotations

import platform
import threading
from collections.abc import Callable

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
    default_model_path,
    download_default_model,
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

        return EnvironmentStatus(
            platform=platform.system().lower() or "unknown",
            runtime_installed=runtime_ready,
            runtime_running=runtime_ready,
            model_dir=str(model_dir),
            embedding_model=embedding_model,
            generation_model=generation_model,
            embedding_model_ready=generation_ready,
            generation_model_ready=generation_ready,
            models=models,
            ready=generation_ready,
            can_auto_install=True,
            install_method=f"download {DEFAULT_MODEL_REPO}",
            message=environment_message(runtime_ready, generation_model, generation_ready, models),
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

            if not llama_cpp_available():
                raise RuntimeError("llama.cpp 런타임이 설치되어 있지 않습니다.")

            generation_model = (request.generation_model or DEFAULT_GENERATION_MODEL).strip()
            if generation_model != DEFAULT_GENERATION_MODEL:
                self._log("models", f"사용자 지정 모델 확인: {generation_model}")
                if resolve_model_path(generation_model, model_dir) is None:
                    raise RuntimeError(f"'{generation_model}' 모델 파일을 찾지 못했습니다. {model_dir} 폴더에 GGUF 모델을 넣어 주세요.")
            else:
                self._log("download", f"기본 로컬 LLM을 준비합니다: {DEFAULT_MODEL_REPO}")
                target = default_model_path(model_dir)
                if target.exists():
                    self._log("download", f"기본 모델이 이미 설치되어 있습니다: {target.name}")
                else:
                    last_bucket = -1

                    def report(downloaded: int, total: int | None) -> None:
                        nonlocal last_bucket
                        bucket = downloaded // (25 * 1024 * 1024)
                        if bucket == last_bucket:
                            return
                        last_bucket = bucket
                        if total:
                            percent = downloaded / total * 100
                            self._log("download", f"모델 다운로드 중: {percent:.1f}%")
                        else:
                            size_mb = downloaded / 1024 / 1024
                            self._log("download", f"모델 다운로드 중: {size_mb:.0f} MB")

                    download_default_model(model_dir, progress=report)
                    self._log("download", f"기본 모델 설치 완료: {DEFAULT_GENERATION_MODEL}")

            self._save_settings(DEFAULT_EMBEDDING_MODEL, generation_model)
            self._log("models", f"로컬 LLM을 사용합니다: {generation_model}")
            self._complete("로컬 LLM 환경 준비 완료")
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
