from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from backend.app.models import EnvironmentSetupProgress, EnvironmentSetupRequest, EnvironmentStatus


OLLAMA_API_BASE = "http://localhost:11434/api"
DEFAULT_EMBEDDING_MODEL = "embeddinggemma"
DEFAULT_GENERATION_MODEL = "qwen2.5:3b"


@dataclass
class SetupState:
    running: bool = False
    stage: str = "idle"
    message: str = "대기 중"
    logs: list[str] = field(default_factory=list)
    error: str | None = None


class EnvironmentSetupManager:
    def __init__(self, save_settings: Callable[[str, str], None]) -> None:
        self._save_settings = save_settings
        self._lock = threading.Lock()
        self._state = SetupState()

    def status(self) -> EnvironmentStatus:
        models = list_ollama_models()
        embedding_model = DEFAULT_EMBEDDING_MODEL
        generation_model = DEFAULT_GENERATION_MODEL
        embedding_ready = has_model(models, embedding_model)
        generation_ready = has_model(models, generation_model)
        running = ollama_api_ready()
        installed = ollama_installed() or running
        return EnvironmentStatus(
            platform=platform.system().lower(),
            ollama_installed=installed,
            ollama_running=running,
            embedding_model=embedding_model,
            generation_model=generation_model,
            embedding_model_ready=embedding_ready,
            generation_model_ready=generation_ready,
            models=models,
            ready=running and embedding_ready and generation_ready,
            can_auto_install=installed,
            install_method="installed Ollama + local model pull" if installed else "manual",
            message=environment_message(installed, running, embedding_ready, generation_ready),
        )

    def progress(self) -> EnvironmentSetupProgress:
        with self._lock:
            return EnvironmentSetupProgress(
                running=self._state.running,
                stage=self._state.stage,
                message=self._state.message,
                logs=list(self._state.logs[-30:]),
                error=self._state.error,
            )

    def start(self, request: EnvironmentSetupRequest) -> EnvironmentSetupProgress:
        with self._lock:
            if self._state.running:
                return EnvironmentSetupProgress(
                    running=self._state.running,
                    stage=self._state.stage,
                    message=self._state.message,
                    logs=list(self._state.logs[-30:]),
                    error=self._state.error,
                )
            self._state = SetupState(running=True, stage="queued", message="환경 설정을 시작합니다.")
        thread = threading.Thread(target=self._run, args=(request,), daemon=True)
        thread.start()
        return self.progress()

    def _run(self, request: EnvironmentSetupRequest) -> None:
        try:
            embedding_model = request.embedding_model or DEFAULT_EMBEDDING_MODEL
            generation_model = request.generation_model or DEFAULT_GENERATION_MODEL
            self._log("detect", "Ollama 설치 상태를 확인합니다.")

            if not ollama_installed() and not ollama_api_ready():
                raise RuntimeError("Ollama가 설치되어 있지 않습니다. 공식 설치 후 다시 시도해 주세요.")

            self._start_ollama()

            if request.pull_embedding_model:
                self._pull_model(embedding_model)
            if request.pull_generation_model:
                self._pull_model(generation_model)

            self._save_settings(embedding_model, generation_model)
            self._log("complete", "로컬 AI 환경 설정이 완료되었습니다.")
            self._finish(None)
        except Exception as error:
            self._log("failed", f"환경 설정 실패: {error}")
            self._finish(str(error))

    def _start_ollama(self) -> None:
        if ollama_api_ready():
            self._log("start", "Ollama가 이미 실행 중입니다.")
            return
        self._log("start", "Ollama를 시작합니다.")
        command = find_ollama_command()
        if command is not None:
            subprocess.Popen(
                [command, "serve"],
                env={**os.environ, "OLLAMA_HOST": "127.0.0.1:11434"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait_for_ollama()
            self._log("start", "Ollama API 연결을 확인했습니다.")
            return
        app_paths = [
            Path.home() / "Applications" / "Ollama.app",
            Path("/Applications/Ollama.app"),
        ]
        app_path = next((path for path in app_paths if path.exists()), None)
        if platform.system() == "Darwin" and app_path is not None:
            subprocess.Popen(["open", str(app_path)])
        else:
            raise RuntimeError("실행할 Ollama 명령 또는 앱을 찾지 못했습니다.")
        wait_for_ollama()
        self._log("start", "Ollama API 연결을 확인했습니다.")

    def _pull_model(self, model: str) -> None:
        if has_model(list_ollama_models(), model):
            self._log("model", f"{model} 모델은 이미 준비되어 있습니다.")
            return
        self._log("model", f"{model} 모델을 다운로드합니다.")
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "POST",
                f"{OLLAMA_API_BASE}/pull",
                json={"model": model, "stream": True},
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    status = str(payload.get("status", "")).strip()
                    completed = payload.get("completed")
                    total = payload.get("total")
                    if completed and total:
                        percent = int((float(completed) / float(total)) * 100)
                        self._log("model", f"{model}: {status} {percent}%")
                    elif status:
                        self._log("model", f"{model}: {status}")

    def _log(self, stage: str, message: str) -> None:
        with self._lock:
            self._state.stage = stage
            self._state.message = message
            if not self._state.logs or self._state.logs[-1] != message:
                self._state.logs.append(message)
                if len(self._state.logs) > 60:
                    self._state.logs = self._state.logs[-30:]

    def _finish(self, error: str | None) -> None:
        with self._lock:
            self._state.running = False
            self._state.error = error
            if error is not None:
                self._state.stage = "failed"
                self._state.message = error


def find_ollama_command() -> str | None:
    candidates = [
        shutil.which("ollama"),
        "/opt/homebrew/bin/ollama",
        "/usr/local/bin/ollama",
        str(Path.home() / "Applications" / "Ollama.app" / "Contents" / "Resources" / "ollama"),
        "/Applications/Ollama.app/Contents/Resources/ollama",
    ]
    return next((candidate for candidate in candidates if candidate and Path(candidate).exists()), None)


def ollama_installed() -> bool:
    return bool(
        find_ollama_command()
        or (Path.home() / "Applications" / "Ollama.app").exists()
        or Path("/Applications/Ollama.app").exists()
    )


def ollama_api_ready() -> bool:
    try:
        with httpx.Client(timeout=1.5) as client:
            response = client.get(f"{OLLAMA_API_BASE}/tags")
            return response.status_code == 200
    except Exception:
        return False


def wait_for_ollama(timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ollama_api_ready():
            return
        time.sleep(1)
    raise RuntimeError("Ollama API가 제한 시간 안에 시작되지 않았습니다.")


def list_ollama_models() -> list[str]:
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(f"{OLLAMA_API_BASE}/tags")
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []
    return [item.get("name", "") for item in payload.get("models", []) if item.get("name")]


def has_model(models: list[str], expected: str) -> bool:
    expected_base = expected.split(":")[0]
    return any(model == expected or model.split(":")[0] == expected_base for model in models)


def environment_message(
    installed: bool,
    running: bool,
    embedding_ready: bool,
    generation_ready: bool,
) -> str:
    if not installed:
        return "Ollama 설치가 필요합니다."
    if not running:
        return "Ollama 실행이 필요합니다."
    if not embedding_ready:
        return f"{DEFAULT_EMBEDDING_MODEL} 임베딩 모델 다운로드가 필요합니다."
    if not generation_ready:
        return f"{DEFAULT_GENERATION_MODEL} 생성 모델 다운로드가 필요합니다."
    return "로컬 AI 환경 준비 완료"
