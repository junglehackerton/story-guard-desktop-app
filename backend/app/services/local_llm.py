from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.app.services.local_ai import DEFAULT_GENERATION_MODEL, llama_cpp_available, resolve_model_path


class LocalLlmExtractor:
    _llm_cache: dict[str, Any] = {}

    def __init__(self, model: str | None = None, model_dir: Path | None = None) -> None:
        self.model = (
            model if model is not None else os.getenv("STORY_GUARD_GENERATION_MODEL", DEFAULT_GENERATION_MODEL)
        ).strip()
        self.model_dir = model_dir

    def enabled(self) -> bool:
        return resolve_model_path(self.model, self.model_dir) is not None and llama_cpp_available()

    def extract_story_facts(self, text: str) -> dict[str, Any]:
        model_path = resolve_model_path(self.model, self.model_dir)
        if model_path is None:
            raise RuntimeError("로컬 LLM 모델이 설치되어 있지 않습니다.")
        if not llama_cpp_available():
            raise RuntimeError("llama.cpp 런타임이 설치되어 있지 않습니다.")
        system_prompt = """
당신은 한국어 장편 서사의 설정 관리 분석기입니다. 원고에서 명시되거나 강하게 암시된 사실만 추출합니다.
반드시 JSON 객체만 출력하고, 설명 문장이나 마크다운 코드를 출력하지 않습니다.
""".strip()
        user_prompt = f"""
다음 한국어 원고에서 Story Guard 설정 그래프에 필요한 정보를 추출하세요.

허용 entity type: character, place, organization, item, event, rule, foreshadowing
허용 issue severity: low, medium, high
허용 issue category: timeline, character_state, world_rule, relationship, unresolved_foreshadowing, contradiction

중요:
- type, severity, category 값에는 위 목록 중 정확히 하나만 넣으세요.
- "character|place|..."처럼 목록 전체를 값으로 쓰지 마세요.
- 원고에 "인물:", "장소:", "조직:", "아이템:", "설정:", "떡밥:"으로 적힌 항목은 반드시 entities에 포함하세요.
- 원고에 근거가 없으면 빈 배열을 쓰세요.

출력 예시:
{{
  "entities": [
    {{"type": "character", "name": "한서윤", "summary": "검은 열쇠를 들고 흑월성에 간 인물", "aliases": ["서윤"]}},
    {{"type": "item", "name": "검은 열쇠", "summary": "봉인된 문과 관련된 물건", "aliases": []}}
  ],
  "relations": [
    {{"source": "한서윤", "target": "검은 열쇠", "type": "소유/사용", "confidence": 0.8}}
  ],
  "issues": []
}}

원고:
{text[:12000]}
""".strip()
        llm = self._load_llm(model_path)
        response = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1600,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = self._parse_json_object(self._response_text(response))
        if not parsed:
            raise RuntimeError("로컬 LLM이 유효한 JSON 분석 결과를 반환하지 않았습니다.")
        return parsed

    def _load_llm(self, model_path: Path) -> Any:
        cache_key = str(model_path)
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]
        from llama_cpp import Llama

        llm = Llama(
            model_path=cache_key,
            n_ctx=8192,
            n_threads=max(os.cpu_count() or 4, 4),
            verbose=False,
        )
        self._llm_cache[cache_key] = llm
        return llm

    def _response_text(self, response: Any) -> str:
        if isinstance(response, dict):
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    return str(first.get("text") or first.get("message", {}).get("content") or "").strip()
            return str(response.get("response", "")).strip()
        return str(response).strip()

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
