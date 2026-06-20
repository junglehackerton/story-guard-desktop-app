from __future__ import annotations

import json
import os
import re
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
ALLOWED_ENTITY_TYPES = {"character", "place", "organization", "item", "event", "rule", "foreshadowing"}
MEMBERSHIP_TARGET_TYPES = {"character", "place", "event"}
ORGANIZATION_CANDIDATE_RE = re.compile(
    r"([가-힣A-Za-z0-9·]{2,}\s+(?:감찰국|경비대)|"
    r"[가-힣A-Za-z0-9·]{2,}(?:감찰국|경비대|상단|상회|조합|원)|왕궁)"
)
ORGANIZATION_SUFFIXES = ("감찰국", "경비대", "상단", "상회", "조합", "왕궁", "원")
SPATIAL_ANCHOR_RE = re.compile(
    r"^([가-힣A-Za-z0-9· ]{1,24}?(?:접견실|서고|항구|복도|계단|광장|거리|궁전|성|방|실))"
    r"(?:\s|의|에서|안|밖|위|아래|창|문턱|문).+"
)
SPATIAL_TERMS = (
    "접견실",
    "서고",
    "항구",
    "창 밖",
    "창밖",
    "문턱",
    "복도",
    "계단",
    "지하",
    "거리",
    "광장",
)
ITEM_TERMS = (
    "열쇠",
    "장부",
    "등잔",
    "검",
    "칼",
    "책",
    "편지",
    "외투",
    "우산",
    "모자",
    "함",
    "제복",
)
ITEM_PREFIX_STOPWORDS = {"전에", "그리고", "안에서", "밖에서", "위에서", "아래에서", "길이의"}
CLAUSE_MARKERS = ("을 ", "를 ", "은 ", "는 ", "이 ", "가 ", "채", "했다", "한다", "왔다", "웃었다", "넘지", "않은")
NAMED_ITEM_RE = re.compile(
    r"([가-힣A-Za-z0-9·]{2,}(?:\s+[가-힣A-Za-z0-9·]{2,}){0,2}\s*"
    r"(?:열쇠|장부|봉인함|등잔|우산|모자|외투|제복))"
)
KOREAN_PARTICLE_LOOKAHEAD = r"(?=$|[\s,.;:!?]|[은는이가을를와과도에에서으로로])"


def llm_thread_count() -> int:
    raw_value = os.getenv("STORY_GUARD_LLM_THREADS", str(DEFAULT_LLM_THREADS)).strip()
    try:
        requested = int(raw_value)
    except ValueError:
        requested = DEFAULT_LLM_THREADS
    available = os.cpu_count() or DEFAULT_LLM_THREADS
    return max(1, min(requested, available, MAX_LLM_THREADS))


def sanitize_story_payload(
    payload: dict[str, Any],
    known_entity_names: list[str] | None = None,
    story_text: str = "",
) -> dict[str, Any]:
    sanitized = LocalLlmExtractor(model="")._normalize_payload(
        payload,
        payload,
        known_entity_names=known_entity_names,
        story_text=story_text,
    )
    if isinstance(payload.get("claims"), list):
        sanitized["claims"] = [claim for claim in payload["claims"] if isinstance(claim, dict)]
    return sanitized


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
- 한 장소의 하위 표현을 여러 노드로 쪼개지 마세요. 장소명에 창, 문, 문턱, 안, 밖, 위, 아래 같은 하위 위치가 붙으면 대표 공간명 하나만 출력하세요.
- 고유 조직명은 반드시 organization 후보로 올리세요. 접미사, 소속 표현, 명령/관할/권한 표현을 근거로 조직과 장소를 구분하세요.
- type 판단 기준:
  - character: 행동하거나 대화하거나 의도를 가진 인물/존재
  - place: 인물이 들어가고, 머물고, 바라보고, 장면이 벌어지는 공간. 방, 항구, 성, 창 밖, 문턱, 복도, 지하, 서고처럼 위치로 쓰이면 place
  - organization: 구성원, 명령, 소속, 권한, 관할을 가진 집단
  - item: 인물이 소유/사용/교환/운반하는 이동 가능한 물건
  - event: 특정 시점에 발생한 사건이나 작전
  - rule: 세계관 법칙, 금기, 계약 조건, 마법/정치 규칙
  - foreshadowing: 아직 회수되지 않은 단서나 복선
- 장소명 뒤에 붙은 창, 문, 문턱, 안, 밖, 위, 아래 같은 공간 위치는 item이 아니라 place로 분류하되 대표 공간명 하나로 합치세요.
- 물건처럼 보이는 명사라도 장면의 위치나 경계로 기능하면 place입니다. 손에 쥐거나 건네거나 장착하는 대상만 item입니다.
- 같은 공간에서 파생된 위치 표현은 대표 공간 하나로 합치고, 동작이 붙은 긴 구절은 ENTITY로 출력하지 마세요.
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

형식 예시. 실제 출력에는 원고에 나온 고유명사만 쓰고, 꺾쇠표시는 출력하지 마세요.
ENTITY|character|<인물명>|<짧은 역할>|
ENTITY|item|<아이템명>|<짧은 기능>|
ENTITY|place|<대표 공간명>|<짧은 공간 설명>|
ENTITY|organization|<조직명>|<짧은 조직 설명>|
ISSUE|medium|contradiction|<이슈 제목>|<짧은 설명>
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
        organization_names = self._extract_named_organization_names(story_text)
        known_names = self._known_entity_names([*entity_names, *organization_names], known_entity_names or [])
        relation_prompt = f"""
다음 한국어 원고에서 Story Guard 설정 그래프에 필요한 관계만 추출하세요.

알려진 엔티티:
{", ".join(known_names[:50])}

중요:
- REL은 최대 40개까지만 출력하세요.
- 원고의 "소속:", "관할:", "본부:", "거점:", "산하:", "관계:" 관계 선언 1줄마다 REL 한 줄을 반드시 출력하세요.
- 인물이 조직에 속하면 조직을 source, 인물을 target으로 두고 소속/조직 관계를 출력하세요.
- 일반 문장 속에서도 조직과 인물의 소속이 드러나면 반드시 관계를 출력하세요.
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

형식 예시. 실제 출력에는 원고에 나온 고유명사만 쓰고, 꺾쇠표시는 출력하지 마세요.
REL|<조직명>|<인물명>|소속/조직|0.9
REL|<인물명>|<아이템명>|소유/사용|0.8
REL|<인물명>|<조직명>|감시/조사|0.78
REL|<인물명>|<인물명>|명령/지휘|0.74
END

{context_section}

원고:
{story_text}
""".strip()
        try:
            relation_payload = self._request_fact_payload(llm, system_prompt, relation_prompt, max_tokens=650)
        except RuntimeError:
            relation_payload = {}
        return self._normalize_payload(entity_payload, relation_payload, known_names, story_text)

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
        story_text: str = "",
    ) -> dict[str, Any]:
        entities: list[dict[str, Any]] = []
        entity_by_name: dict[str, dict[str, Any]] = {}
        canonical_by_term: dict[str, str] = {}
        for known_name in known_entity_names or []:
            if known_name:
                canonical_by_term.setdefault(known_name, known_name)

        def add_entity(entity: dict[str, Any], raw_terms: list[str] | None = None) -> None:
            existing = entity_by_name.get(entity["name"])
            if existing is not None:
                existing_aliases = set(existing["aliases"])
                for alias in entity["aliases"]:
                    if alias not in existing_aliases:
                        existing["aliases"].append(alias)
                        existing_aliases.add(alias)
                if existing["type"] != "organization" and entity["type"] == "organization":
                    existing["type"] = "organization"
                for raw_term in raw_terms or []:
                    if raw_term:
                        canonical_by_term[raw_term] = existing["name"]
                return
            entities.append(entity)
            entity_by_name[entity["name"]] = entity
            canonical_by_term[entity["name"]] = entity["name"]
            for raw_term in raw_terms or []:
                if raw_term:
                    canonical_by_term[raw_term] = entity["name"]
            for alias in entity["aliases"]:
                canonical_by_term.setdefault(alias, entity["name"])

        for raw_entity in entity_payload.get("entities", []):
            if not isinstance(raw_entity, dict):
                continue
            raw_name = self._clean_entity_name(str(raw_entity.get("name", "")))
            entity = self._normalize_entity(raw_entity, story_text)
            if entity is None:
                continue
            add_entity(entity, [raw_name])

        for organization_name in self._extract_named_organization_names(story_text):
            add_entity(
                {
                    "type": "organization",
                    "name": organization_name,
                    "summary": "조직",
                    "aliases": [],
                }
            )

        for item_name in self._extract_named_item_names(story_text):
            add_entity(
                {
                    "type": "item",
                    "name": item_name,
                    "summary": item_name,
                    "aliases": [],
                }
            )

        relations: list[dict[str, Any]] = []
        seen_relations: set[tuple[str, str, str]] = set()

        def add_relation(source: str, target: str, relation_type: str, confidence: float) -> None:
            key = (source, target, relation_type)
            if key in seen_relations:
                return
            seen_relations.add(key)
            relations.append(
                {
                    "source": source,
                    "target": target,
                    "type": relation_type,
                    "confidence": max(0.0, min(confidence, 1.0)),
                }
            )

        for raw_relation in relation_payload.get("relations", []):
            if not isinstance(raw_relation, dict):
                continue
            source = self._canonical_relation_term(str(raw_relation.get("source", "")).strip(), canonical_by_term)
            target = self._canonical_relation_term(str(raw_relation.get("target", "")).strip(), canonical_by_term)
            relation_type = str(raw_relation.get("type", "")).strip()
            if not source or not target or source == target or not relation_type:
                continue
            source_entity = entity_by_name.get(source)
            target_entity = entity_by_name.get(target)
            if self._is_membership_relation_type(relation_type):
                if (
                    source_entity
                    and target_entity
                    and source_entity["type"] == "organization"
                    and target_entity["type"] in MEMBERSHIP_TARGET_TYPES
                ):
                    if not self._has_membership_evidence(story_text, source_entity, target_entity):
                        continue
                    relation_type = "소속/조직"
                elif (
                    source_entity
                    and target_entity
                    and target_entity["type"] == "organization"
                    and source_entity["type"] in MEMBERSHIP_TARGET_TYPES
                ):
                    if not self._has_membership_evidence(story_text, target_entity, source_entity):
                        continue
                    source, target = target, source
                    relation_type = "소속/조직"
                else:
                    continue
            elif self._is_organization_to_person_guess(source_entity, target_entity):
                continue
            elif self._is_unsupported_organization_item_relation(
                story_text,
                source_entity,
                target_entity,
                relation_type,
            ):
                continue
            try:
                confidence = float(raw_relation.get("confidence", 0.7) or 0.7)
            except (TypeError, ValueError):
                confidence = 0.7
            add_relation(source, target, relation_type, confidence)

        for relation in self._extract_explicit_membership_relations(story_text, entity_by_name):
            add_relation(
                str(relation["source"]),
                str(relation["target"]),
                "소속/조직",
                float(relation.get("confidence", 0.95)),
            )

        return {
            "entities": entities,
            "relations": relations,
            "issues": entity_payload.get("issues", []),
        }

    def _normalize_entity(self, raw_entity: dict[str, Any], story_text: str = "") -> dict[str, Any] | None:
        raw_name = self._clean_entity_name(str(raw_entity.get("name", "")))
        if not raw_name:
            return None
        name = self._collapse_spatial_entity_name(raw_name)
        if self._looks_like_sentence_fragment(raw_name) and name == raw_name:
            return None
        if not name or len(name) > 40:
            return None
        raw_type = str(raw_entity.get("type", "")).strip().lower()
        entity_type = raw_type if raw_type in ALLOWED_ENTITY_TYPES else "item"
        entity_type = self._repair_entity_type(entity_type, name)
        if entity_type == "item":
            name = self._normalize_named_item_candidate(name)
            if len(name) < 2 or self._is_weak_item_phrase(name):
                return None
        name = self._expand_entity_name(name, entity_type, story_text)
        entity_type = self._repair_entity_type(entity_type, name)
        aliases = [
            alias
            for alias in (
                self._clean_entity_name(str(alias))
                for alias in raw_entity.get("aliases", [])
                if self._clean_entity_name(str(alias))
            )
            if alias != name and len(alias) <= 40 and not self._looks_like_sentence_fragment(alias)
        ]
        if raw_name != name and raw_name not in aliases:
            aliases.append(raw_name)
        return {
            "type": entity_type,
            "name": name,
            "summary": str(raw_entity.get("summary", "")).strip()[:120],
            "aliases": aliases,
        }

    def _repair_entity_type(self, entity_type: str, name: str) -> str:
        if self._looks_like_organization_name(name):
            return "organization"
        if entity_type == "item" and self._looks_like_spatial_name(name):
            return "place"
        return entity_type

    def _canonical_relation_term(self, raw_name: str, canonical_by_term: dict[str, str]) -> str | None:
        name = self._clean_entity_name(raw_name)
        if not name:
            return None
        if name in canonical_by_term:
            return canonical_by_term[name]
        collapsed = self._collapse_spatial_entity_name(name)
        return canonical_by_term.get(collapsed)

    def _extract_named_organization_names(self, text: str) -> list[str]:
        names: list[str] = []
        for match in ORGANIZATION_CANDIDATE_RE.finditer(text):
            name = self._clean_entity_name(match.group(1))
            if name and name not in names:
                names.append(name)
        return names

    def _extract_named_item_names(self, text: str) -> list[str]:
        names: list[str] = []
        for match in NAMED_ITEM_RE.finditer(text):
            if text[match.end() : match.end() + 8].startswith(" 관리인"):
                continue
            name = self._normalize_named_item_candidate(match.group(1))
            if self._is_weak_item_phrase(name):
                continue
            if name and name not in names:
                names.append(name)
        return [
            name
            for name in names
            if not (
                len(name.split()) == 1
                and any(other != name and other.endswith(f" {name}") for other in names)
            )
        ]

    def _expand_entity_name(self, name: str, entity_type: str, story_text: str) -> str:
        if not story_text:
            return name
        if entity_type == "character":
            return self._expand_character_name(name, story_text)
        if entity_type == "item":
            return self._expand_item_name(name, story_text)
        return name

    def _expand_character_name(self, name: str, story_text: str) -> str:
        if len(name) >= 3:
            return name
        escaped_name = re.escape(name)
        candidates = [
            self._clean_entity_name(match.group(1))
            for match in re.finditer(rf"([가-힣]{{1,2}}{escaped_name}){KOREAN_PARTICLE_LOOKAHEAD}", story_text)
        ]
        candidates = [candidate for candidate in candidates if len(name) < len(candidate) <= 4]
        return max(candidates, key=len) if candidates else name

    def _expand_item_name(self, name: str, story_text: str) -> str:
        if len(name) < 2:
            return name
        escaped_name = re.escape(name)
        candidates: list[str] = []
        for match in re.finditer(
                rf"([가-힣A-Za-z0-9·]{{2,}}(?:\s+[가-힣A-Za-z0-9·]{{2,}}){{0,2}}\s*{escaped_name})"
                rf"{KOREAN_PARTICLE_LOOKAHEAD}",
                story_text,
        ):
            if story_text[match.end() : match.end() + 8].startswith(" 관리인"):
                continue
            candidates.append(self._normalize_named_item_candidate(match.group(1)))
        candidates = [
            candidate
            for candidate in candidates
            if len(candidate) > len(name) and not self._is_weak_item_phrase(candidate)
        ]
        return min(candidates, key=len) if candidates else name

    def _normalize_named_item_candidate(self, name: str) -> str:
        tokens = self._clean_entity_name(name).split()
        if len(tokens) > 2:
            tokens = tokens[-2:]
        while len(tokens) > 1 and (
            tokens[0] in ITEM_PREFIX_STOPWORDS or (len(tokens[0]) >= 3 and re.search(r"[은는이가]$", tokens[0]))
        ):
            tokens = tokens[1:]
        return self._clean_entity_name(" ".join(tokens))

    def _extract_explicit_membership_relations(
        self,
        story_text: str,
        entity_by_name: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not story_text:
            return []
        organizations = [entity for entity in entity_by_name.values() if entity["type"] == "organization"]
        members = [entity for entity in entity_by_name.values() if entity["type"] in MEMBERSHIP_TARGET_TYPES]
        relations: list[dict[str, Any]] = []
        for organization in organizations:
            for member in members:
                if self._has_membership_evidence(story_text, organization, member):
                    relations.append(
                        {
                            "source": organization["name"],
                            "target": member["name"],
                            "confidence": 0.95,
                        }
                    )
        return relations

    def _has_membership_evidence(self, story_text: str, organization: dict[str, Any], member: dict[str, Any]) -> bool:
        if not story_text:
            return False
        organization_name = re.escape(str(organization["name"]))
        organization_term = rf"{organization_name}(?!\s*(?:감찰국|경비대|상단|상회|조합))"
        role_after_org = r"(?:장|대장|\s+(?:관리인|감찰관|기록관|요원|사람))"
        role_after_possessive = r"[^\n.。!?]{0,20}(?:대장|관리인|감찰관|기록관|요원|사람)"
        member_terms = [
            re.escape(term)
            for term in [str(member["name"]), *[str(alias) for alias in member.get("aliases", [])]]
            if term
        ]
        if not member_terms:
            return False
        for member_name in member_terms:
            if re.search(
                rf"{member_name}[은는이가]?[^\n.。!?]{{0,50}}{organization_term}"
                rf"(?:의\s*{role_after_possessive}|\s*소속|{role_after_org})",
                story_text,
            ):
                return True
            if re.search(
                rf"{member_name}[은는이가]?[^\n.。!?]{{0,80}}[.。!?]\s*"
                rf"(?:그는|그가|그녀는|그녀가|그)[^\n.。!?]{{0,50}}"
                rf"{organization_term}{role_after_org}",
                story_text,
            ):
                return True
            if re.search(
                rf"{organization_term}"
                rf"(?:\s*소속| 사람|의\s*{role_after_possessive})"
                rf"[^\n.。!?]{{0,40}}{member_name}",
                story_text,
            ):
                return True
            if re.search(
                rf"{organization_term}의[^\n.。!?]{{0,24}}제복[^\n.。!?]{{0,24}}(?:서 있었다|있었다)[.。!?]?\s*{member_name}",
                story_text,
            ):
                return True
        return False

    def _is_membership_relation_type(self, relation_type: str) -> bool:
        relation_type = relation_type.lower()
        return any(term in relation_type for term in ("소속", "조직", "member", "belongs", "affiliated"))

    def _is_organization_to_person_guess(
        self,
        source_entity: dict[str, Any] | None,
        target_entity: dict[str, Any] | None,
    ) -> bool:
        return bool(
            source_entity
            and target_entity
            and source_entity["type"] == "organization"
            and target_entity["type"] == "character"
        )

    def _is_unsupported_organization_item_relation(
        self,
        story_text: str,
        source_entity: dict[str, Any] | None,
        target_entity: dict[str, Any] | None,
        relation_type: str,
    ) -> bool:
        if not (
            source_entity
            and target_entity
            and source_entity["type"] == "organization"
            and target_entity["type"] == "item"
            and any(term in relation_type for term in ("소유", "사용", "owns", "use"))
        ):
            return False
        return not self._has_organization_item_evidence(story_text, source_entity, target_entity)

    def _has_organization_item_evidence(
        self,
        story_text: str,
        organization: dict[str, Any],
        item: dict[str, Any],
    ) -> bool:
        if not story_text:
            return False
        organization_name = re.escape(str(organization["name"]))
        organization_term = rf"{organization_name}(?!\s*(?:감찰국|경비대|상단|상회|조합))"
        item_terms = [
            re.escape(term)
            for term in [str(item["name"]), *[str(alias) for alias in item.get("aliases", [])]]
            if term
        ]
        for item_name in item_terms:
            if re.search(rf"{organization_term}의[^\n.。!?]{{0,20}}{item_name}", story_text):
                return True
            if re.search(
                rf"{item_name}[은는이가]?[^\n.。!?]{{0,50}}{organization_term}"
                rf"[은는이가]?[^\n.。!?]{{0,30}}(?:보관|관리|소유|사용|기록|지키|적어)",
                story_text,
            ):
                return True
        return False

    def _is_weak_item_phrase(self, name: str) -> bool:
        return name.startswith(("젖은 ", "푸른 ", "흰 ", "그 ")) or name.endswith("냄새")

    def _looks_like_organization_name(self, name: str) -> bool:
        return name == "왕궁" or any(name.endswith(suffix) for suffix in ORGANIZATION_SUFFIXES)

    def _looks_like_spatial_name(self, name: str) -> bool:
        if any(term in name for term in ITEM_TERMS):
            return False
        return any(term in name for term in SPATIAL_TERMS)

    def _collapse_spatial_entity_name(self, name: str) -> str:
        compact_name = self._clean_entity_name(name)
        if self._looks_like_organization_name(compact_name):
            return compact_name
        match = SPATIAL_ANCHOR_RE.match(compact_name)
        if match:
            return self._clean_entity_name(match.group(1))
        return compact_name

    def _looks_like_sentence_fragment(self, name: str) -> bool:
        if len(name) > 40:
            return True
        return len(name) > 18 and any(marker in name for marker in CLAUSE_MARKERS)

    def _clean_entity_name(self, name: str) -> str:
        return re.sub(r"\s+", " ", name).strip().strip("\"'“”‘’.,;:!?()[]{}")

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
