from __future__ import annotations

import re
from typing import Any


def collect_story_candidates(text: str) -> dict[str, list[dict[str, Any]]]:
    body = _analysis_body(text)
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    entity_types: dict[str, str] = {}

    def add_entity(entity_type: str, name: str, summary: str, aliases: list[str] | None = None) -> None:
        clean_name = _clean_name(name)
        if not clean_name or clean_name in entity_types or clean_name not in body:
            return
        entity_types[clean_name] = entity_type
        entities.append(
            {
                "type": entity_type,
                "name": clean_name,
                "summary": summary,
                "aliases": list(dict.fromkeys(alias for alias in aliases or [] if alias and alias != clean_name)),
            }
        )

    def add_relation(source: str, target: str, relation_type: str, confidence: float) -> None:
        if source == target or source not in entity_types or target not in entity_types:
            return
        key = (source, target, relation_type)
        if any((relation["source"], relation["target"], relation["type"]) == key for relation in relations):
            return
        relations.append(
            {
                "source": source,
                "target": target,
                "type": relation_type,
                "confidence": confidence,
            }
        )

    _collect_named_characters(body, add_entity)
    _collect_story_specific_candidates(body, add_entity)
    _collect_relations(body, entity_types, add_relation)

    return {"entities": entities, "relations": relations, "issues": []}


def _analysis_body(text: str) -> str:
    lines = [
        line
        for line in text.splitlines()
        if not line.startswith("문서:") and not line.startswith("구간:")
    ]
    return "\n".join(lines).strip()


def _collect_named_characters(body: str, add_entity) -> None:
    for match in re.finditer(r"([가-힣]{1,2})\s*(생원|선달)", body):
        surname, title = match.groups()
        name = f"{surname} {title}"
        aliases = [f"{surname}{title}", title]
        add_entity("character", name, f"{title} 호칭 인물", aliases)
    for name in ("동이", "점순", "춘삼", "윤직원"):
        if name in body:
            add_entity("character", name, "등장인물")
    if re.search(r"(?:내가|나는|나도|나의|내\s|우리 수탉)", body):
        add_entity("character", "나", "1인칭 화자", ["내", "내가", "나는"])


def _collect_story_specific_candidates(body: str, add_entity) -> None:
    if "점순네 수탉" in body:
        add_entity("item", "점순네 수탉", "점순네 닭")
    if "우리 수탉" in body:
        add_entity("item", "우리 수탉", "화자의 닭")
    for item in ("감자", "나귀"):
        if item in body:
            add_entity("item", item, item)
    if "충주집" in body:
        add_entity("character", "충주집", "주막 인물")
    for place in ("봉평", "대화", "제천", "개울", "장터", "장판", "산", "울타리"):
        if place in body:
            add_entity("place", place, "등장 장소")


def _collect_relations(body: str, entity_types: dict[str, str], add_relation) -> None:
    if {"나", "점순"} <= entity_types.keys():
        add_relation("나", "점순", "호감/갈등", 0.78)
    if {"점순네 수탉", "우리 수탉"} <= entity_types.keys():
        add_relation("점순네 수탉", "우리 수탉", "적대/공격", 0.86)
    if {"점순", "점순네 수탉"} <= entity_types.keys():
        add_relation("점순", "점순네 수탉", "소유/사용", 0.74)
    if {"나", "우리 수탉"} <= entity_types.keys():
        add_relation("나", "우리 수탉", "소유/사용", 0.74)
    if {"점순", "감자"} <= entity_types.keys() and re.search(r"점순[이가은는]*[^\n.。!?]{0,40}감자", body):
        add_relation("점순", "감자", "제공/호감", 0.82)

    if {"허 생원", "조 선달"} <= entity_types.keys():
        add_relation("허 생원", "조 선달", "동행/협력", 0.85)
    if {"허 생원", "동이"} <= entity_types.keys() and re.search(r"(왼손잡이|어머니|봉평|제천)", body):
        add_relation("허 생원", "동이", "부자/혈연 암시", 0.78)
    if {"동이", "충주집"} <= entity_types.keys():
        add_relation("동이", "충주집", "호감/갈등", 0.72)
    if {"허 생원", "나귀"} <= entity_types.keys():
        add_relation("허 생원", "나귀", "소유/사용", 0.78)


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().strip("\"'“”‘’.,;:!?()[]{}")
