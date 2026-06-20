from __future__ import annotations

import json
import os
from typing import Any

import httpx


class LocalLlmExtractor:
    def __init__(self, base_url: str = "http://localhost:11434/api", model: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = (model if model is not None else os.getenv("STORY_GUARD_GENERATION_MODEL", "")).strip()

    def enabled(self) -> bool:
        return bool(self.model)

    def extract_story_facts(self, text: str) -> dict[str, Any]:
        if not self.model:
            return {}
        prompt = f"""
다음 한국어 원고에서 Story Guard 설정 그래프에 필요한 정보를 JSON으로만 추출하세요.

스키마:
{{
  "entities": [
    {{"type": "character|place|organization|item|event|rule|foreshadowing", "name": "이름", "summary": "짧은 설명", "aliases": []}}
  ],
  "relations": [
    {{"source": "엔티티 이름", "target": "엔티티 이름", "type": "관계", "confidence": 0.0}}
  ],
  "issues": [
    {{"severity": "low|medium|high", "category": "timeline|character_state|world_rule|relationship|unresolved_foreshadowing|contradiction", "title": "제목", "description": "근거 포함 설명"}}
  ]
}}

원고:
{text[:12000]}
""".strip()
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{self.base_url}/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            raw = str(response.json().get("response", "")).strip()
        return self._parse_json_object(raw)

    def _parse_json_object(self, raw: str) -> dict[str, Any]:
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.removeprefix("json").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
