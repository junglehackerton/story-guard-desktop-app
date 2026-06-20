from __future__ import annotations

import httpx

from backend.app.models import OllamaHealth


def _model_names(payload: dict) -> list[str]:
    return [item.get("name", "") for item in payload.get("models", []) if item.get("name")]


def _generation_model_names(payload: dict) -> list[str]:
    models: list[str] = []
    for item in payload.get("models", []):
        name = item.get("name", "")
        if not name:
            continue
        capabilities = item.get("capabilities", [])
        if "completion" in capabilities:
            models.append(name)
    return models


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434/api") -> None:
        self.base_url = base_url.rstrip("/")

    async def health(self) -> OllamaHealth:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self.base_url}/tags")
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError:
            return OllamaHealth(
                ok=False,
                base_url=self.base_url,
                message="Ollama가 설치되어 있지 않거나 실행 중이 아닙니다. Ollama를 실행한 뒤 embeddinggemma 모델을 받아 주세요.",
            )
        except Exception as error:
            return OllamaHealth(
                ok=False,
                base_url=self.base_url,
                message=f"Ollama 상태 확인 실패: {error}",
            )

        all_models = _model_names(payload)
        generation_models = _generation_model_names(payload)
        if "embeddinggemma" not in {model.split(":")[0] for model in all_models}:
            return OllamaHealth(
                ok=False,
                base_url=self.base_url,
                message="Ollama는 실행 중이지만 embeddinggemma 모델이 없습니다. `ollama pull embeddinggemma`가 필요합니다.",
                models=generation_models,
            )
        return OllamaHealth(
            ok=True,
            base_url=self.base_url,
            message="Ollama 연결 성공",
            models=generation_models,
        )

    async def embed(self, texts: list[str], model: str = "embeddinggemma") -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/embed",
                json={"model": model, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
        return payload.get("embeddings", [])

    async def generate(self, prompt: str, model: str) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            payload = response.json()
        return str(payload.get("response", ""))
