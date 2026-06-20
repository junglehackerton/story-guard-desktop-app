from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.app.services.local_ai import (
    DEFAULT_GENERATION_MODEL,
    llama_cpp_available,
    llama_gpu_layer_count,
    resolve_model_path,
)


DEFAULT_LLM_THREADS = 1
MAX_LLM_THREADS = 4
MAX_STORY_CHARS_PER_PROMPT = 2400
MAX_CONTEXT_CHARS_PER_PROMPT = 700


def llm_thread_count() -> int:
    raw_value = os.getenv("STORY_GUARD_LLM_THREADS", str(DEFAULT_LLM_THREADS)).strip()
    try:
        requested = int(raw_value)
    except ValueError:
        requested = DEFAULT_LLM_THREADS
    available = os.cpu_count() or DEFAULT_LLM_THREADS
    return max(1, min(requested, available, MAX_LLM_THREADS))


class LocalLlmExtractor:
    _llm_cache: dict[str, Any] = {}

    def __init__(self, model: str | None = None, model_dir: Path | None = None) -> None:
        self.model = (
            model if model is not None else os.getenv("STORY_GUARD_GENERATION_MODEL", DEFAULT_GENERATION_MODEL)
        ).strip()
        self.model_dir = model_dir

    def enabled(self) -> bool:
        return resolve_model_path(self.model, self.model_dir) is not None and llama_cpp_available()

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict[str, Any]:
        model_path = resolve_model_path(self.model, self.model_dir)
        if model_path is None:
            raise RuntimeError("로컬 LLM 모델이 설치되어 있지 않습니다.")
        if not llama_cpp_available():
            raise RuntimeError("llama.cpp 런타임이 설치되어 있지 않습니다.")
        system_prompt = """
당신은 한국어 장편 서사의 설정 관리 분석기입니다. 원고에서 명시되거나 강하게 암시된 사실만 추출합니다.
반드시 지정된 줄 형식만 출력하고, 설명 문장이나 마크다운 코드를 출력하지 않습니다.
""".strip()
        llm = self._load_llm(model_path)
        story_text = text[:MAX_STORY_CHARS_PER_PROMPT]
        context_section = self._context_section(context)

        entity_prompt = f"""
다음 한국어 원고에서 Story Guard 설정 그래프에 필요한 엔티티와 설정 이슈만 추출하세요.

허용 entity type: character, place, organization, item, event, rule, foreshadowing
허용 issue severity: low, medium, high
허용 issue category: timeline, character_state, world_rule, relationship, unresolved_foreshadowing, contradiction

중요:
- ENTITY는 핵심 명명 개념만 최대 24개, ISSUE는 최대 8개까지만 출력하세요.
- summary는 12자 안팎의 명사구만 쓰고, description은 25자 안팎으로 짧게 쓰세요.
- aliases에는 별칭만 쉼표로 쓰세요. 별칭이 없으면 빈칸으로 두고, 설명 문장이나 원문 문장을 넣지 마세요.
- type, severity, category 값에는 위 목록 중 정확히 하나만 넣으세요.
- "character|place|..."처럼 목록 전체를 값으로 쓰지 마세요.
- 원고가 별도 설정표 없이 일반 소설 문장만으로 구성되어 있어도 반복 등장하는 고유명사와 서사적으로 중요한 개념을 추출하세요.
- 원고에 "인물:", "장소:", "조직:", "아이템:", "설정:", "떡밥:"으로 적힌 항목이 있으면 참고하되, 선언형 항목이 없어도 추출을 멈추지 마세요.
- 원고에 근거가 없는 항목은 출력하지 마세요.
- 관계는 출력하지 마세요. REL 줄은 다음 단계에서 따로 추출합니다.

반드시 아래 줄 형식만 사용하세요. 각 필드는 | 로 구분합니다.
ENTITY|type|name|summary|aliases
ISSUE|severity|category|title|description
END

예시:
ENTITY|character|한서윤|기록관|서윤
ENTITY|item|검은 열쇠|봉인 열쇠|
ENTITY|organization|백야단|서고 조직|
ISSUE|medium|contradiction|왕좌 혈통 충돌|초반과 후반의 혈통 설명이 다르다.
END

{context_section}

원고:
{story_text}
""".strip()
        entity_payload = self._request_fact_payload(llm, system_prompt, entity_prompt, max_tokens=850)
        if not entity_payload:
            raise RuntimeError("로컬 LLM이 분석 결과 형식을 완성하지 못했습니다. 다시 분석을 실행해 주세요.")

        entity_names = [
            str(entity.get("name", "")).strip()
            for entity in entity_payload.get("entities", [])
            if isinstance(entity, dict) and str(entity.get("name", "")).strip()
        ]
        known_names = self._known_entity_names(entity_names, known_entity_names or [])
        relation_prompt = f"""
다음 한국어 원고에서 Story Guard 설정 그래프에 필요한 관계만 추출하세요.

알려진 엔티티:
{", ".join(known_names[:50])}

중요:
- REL은 최대 40개까지만 출력하세요.
- 원고의 "소속:", "관할:", "본부:", "거점:", "산하:", "관계:" 관계 선언 1줄마다 REL 한 줄을 반드시 출력하세요.
- "소속: 한서윤 -> 백야단"처럼 인물이 조직에 속하면 REL|백야단|한서윤|소속/조직|0.9 로 출력하세요.
- "본부:", "거점:", "관할:"처럼 조직이 개념을 포함하거나 관리하면 조직을 source, 속한 개념을 target으로 출력하세요.
- 원고 앞에 관계표가 없어도 대화, 행동, 추격, 보호, 명령, 거래, 조사, 배신, 소유, 사용 장면에서 관계를 추론하세요.
- 선언형 소속/포함 관계뿐 아니라 서사 문장 속 협력, 적대, 감시, 명령, 조사, 소유/사용, 비밀 거래 관계도 출력하세요.
- 같은 조직 안의 인물 간 관계가 명시되면 조직 소속과 별도로 인물-인물 REL을 반드시 출력하세요.
- 인물과 조직, 조직과 조직, 인물과 아이템, 인물과 사건 사이의 직접 상호작용도 누락하지 마세요.
- 일반 관계 confidence는 근거가 명확하면 0.7 이상으로 쓰세요.
- 알려진 엔티티 이름을 source와 target에 그대로 쓰세요.
- 근거가 없는 관계는 출력하지 마세요.

반드시 아래 줄 형식만 사용하세요. 각 필드는 | 로 구분합니다.
REL|source|target|type|confidence
END

예시:
REL|백야단|한서윤|소속/조직|0.9
REL|한서윤|검은 열쇠|소유/사용|0.8
REL|백무진|은하 밀수조합|비밀/거래|0.86
REL|서리안|백야단|감시/조사|0.78
REL|백무진|윤하린|명령/지휘|0.74
END

{context_section}

원고:
{story_text}
""".strip()
        try:
            relation_payload = self._request_fact_payload(llm, system_prompt, relation_prompt, max_tokens=650)
        except RuntimeError:
            relation_payload = {}
        return self._normalize_payload(entity_payload, relation_payload, known_names)

    def _request_fact_payload(self, llm: Any, system_prompt: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
        try:
            response = llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.0,
                stop=["\nEND", "END"],
            )
        except Exception as error:
            if "context window" in str(error) or "Requested tokens" in str(error):
                raise RuntimeError(
                    "원고 구간이 로컬 모델 컨텍스트를 초과했습니다. 원고를 더 작은 회차로 나누어 다시 분석해 주세요."
                ) from error
            raise
        parsed = self._parse_fact_lines(self._response_text(response))
        if not parsed:
            raise RuntimeError("로컬 LLM이 분석 결과 형식을 완성하지 못했습니다. 다시 분석을 실행해 주세요.")
        return parsed

    def detect_continuity_issues(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        model_path = resolve_model_path(self.model, self.model_dir)
        if model_path is None:
            raise RuntimeError("로컬 LLM 모델이 설치되어 있지 않습니다.")
        if not llama_cpp_available():
            raise RuntimeError("llama.cpp 런타임이 설치되어 있지 않습니다.")
        system_prompt = """
당신은 한국어 장편 서사의 설정 붕괴 감시자입니다. 이전 회차와 현재 회차의 모순 후보만 짧게 추출합니다.
반드시 지정된 줄 형식만 출력하고, 설명 문장이나 마크다운 코드를 출력하지 않습니다.
""".strip()
        known_names = self._known_entity_names([], known_entity_names or [])
        prompt = f"""
다음 누적 분석 요약과 회차 발췌를 비교해서 설정 붕괴 후보만 추출하세요.

허용 issue severity: low, medium, high
허용 issue category: timeline, character_state, world_rule, relationship, unresolved_foreshadowing, contradiction

중요:
- 5편 이상 쌓인 뒤의 장기 연속성 문제만 보세요.
- 같은 회차 안의 단순 오해나 반전 가능성은 high로 단정하지 마세요.
- 초반 규칙/관계/상태와 후반 설명이 충돌하면 ISSUE를 출력하세요.
- 근거가 약하면 출력하지 마세요.
- 엔티티나 관계는 출력하지 말고 설정 붕괴 후보만 출력하세요.

알려진 엔티티:
{", ".join(known_names[:50])}

반드시 아래 줄 형식만 사용하세요. 각 필드는 | 로 구분합니다.
ISSUE|severity|category|title|description
END

예시:
ISSUE|high|world_rule|푸른 등화 혈통 규칙 충돌|초반에는 회백원의 피가 필요했지만 후반에는 무관하다고 나온다.
END

{self._context_section(context)}

회차 발췌:
{text[:MAX_STORY_CHARS_PER_PROMPT]}
""".strip()
        payload = self._request_fact_payload(self._load_llm(model_path), system_prompt, prompt, max_tokens=450)
        issues = payload.get("issues", [])
        return [issue for issue in issues if isinstance(issue, dict)]

    def _normalize_payload(
        self,
        entity_payload: dict[str, Any],
        relation_payload: dict[str, Any],
        known_entity_names: list[str] | None = None,
    ) -> dict[str, Any]:
        entities: list[dict[str, Any]] = []
        canonical_by_term: dict[str, str] = {}
        for known_name in known_entity_names or []:
            if known_name:
                canonical_by_term.setdefault(known_name, known_name)
        seen_entities: set[str] = set()
        for raw_entity in entity_payload.get("entities", []):
            if not isinstance(raw_entity, dict):
                continue
            name = str(raw_entity.get("name", "")).strip()
            if not name or name in seen_entities:
                continue
            seen_entities.add(name)
            aliases = [
                alias
                for alias in (
                    str(alias).strip()
                    for alias in raw_entity.get("aliases", [])
                    if str(alias).strip()
                )
                if alias != name and len(alias) <= 40
            ]
            entity = {
                "type": str(raw_entity.get("type", "")).strip(),
                "name": name,
                "summary": str(raw_entity.get("summary", "")).strip()[:120],
                "aliases": aliases,
            }
            entities.append(entity)
            canonical_by_term[name] = name
            for alias in aliases:
                canonical_by_term.setdefault(alias, name)

        relations: list[dict[str, Any]] = []
        seen_relations: set[tuple[str, str, str]] = set()
        for raw_relation in relation_payload.get("relations", []):
            if not isinstance(raw_relation, dict):
                continue
            source = canonical_by_term.get(str(raw_relation.get("source", "")).strip())
            target = canonical_by_term.get(str(raw_relation.get("target", "")).strip())
            relation_type = str(raw_relation.get("type", "")).strip()
            if not source or not target or source == target or not relation_type:
                continue
            key = (source, target, relation_type)
            if key in seen_relations:
                continue
            seen_relations.add(key)
            try:
                confidence = float(raw_relation.get("confidence", 0.7) or 0.7)
            except (TypeError, ValueError):
                confidence = 0.7
            relations.append(
                {
                    "source": source,
                    "target": target,
                    "type": relation_type,
                    "confidence": max(0.0, min(confidence, 1.0)),
                }
            )

        return {
            "entities": entities,
            "relations": relations,
            "issues": entity_payload.get("issues", []),
        }

    def _context_section(self, context: str) -> str:
        compact_context = context.strip()[:MAX_CONTEXT_CHARS_PER_PROMPT]
        if not compact_context:
            return ""
        return f"기존 분석 요약:\n{compact_context}"

    def _known_entity_names(self, entity_names: list[str], previous_entity_names: list[str]) -> list[str]:
        names: list[str] = []
        for raw_name in [*previous_entity_names, *entity_names]:
            name = str(raw_name).strip()
            if name and name not in names:
                names.append(name)
        return names

    def _load_llm(self, model_path: Path) -> Any:
        cache_key = str(model_path)
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]
        from llama_cpp import Llama

        threads = llm_thread_count()
        llm = Llama(
            model_path=cache_key,
            n_ctx=4096,
            n_threads=threads,
            n_threads_batch=threads,
            n_gpu_layers=llama_gpu_layer_count(),
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
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as error:
            raise ValueError("로컬 LLM JSON 응답을 파싱할 수 없습니다.") from error
        return parsed if isinstance(parsed, dict) else {}

    def _parse_fact_lines(self, raw: str) -> dict[str, Any]:
        try:
            json_payload = self._parse_json_object(raw)
        except ValueError:
            json_payload = {}
        if json_payload:
            return json_payload

        payload: dict[str, list[dict[str, Any]]] = {
            "entities": [],
            "relations": [],
            "issues": [],
        }
        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line or line == "END" or line.startswith("```"):
                continue
            parts = [part.strip() for part in line.split("|")]
            kind = parts[0].upper() if parts else ""
            if kind == "ENTITY" and len(parts) >= 5 and len(payload["entities"]) < 30:
                entity_type, name, summary, aliases = parts[1], parts[2], parts[3], parts[4]
                payload["entities"].append(
                    {
                        "type": entity_type,
                        "name": name,
                        "summary": summary,
                        "aliases": [alias.strip() for alias in aliases.split(",") if alias.strip()],
                    }
                )
            elif kind == "REL" and len(parts) >= 5 and len(payload["relations"]) < 60:
                try:
                    confidence = float(parts[4])
                except ValueError:
                    confidence = 0.7
                payload["relations"].append(
                    {
                        "source": parts[1],
                        "target": parts[2],
                        "type": parts[3],
                        "confidence": confidence,
                    }
                )
            elif kind == "ISSUE" and len(parts) >= 5 and len(payload["issues"]) < 12:
                payload["issues"].append(
                    {
                        "severity": parts[1],
                        "category": parts[2],
                        "title": parts[3],
                        "description": parts[4],
                    }
                )

        return payload if payload["entities"] or payload["relations"] or payload["issues"] else {}
