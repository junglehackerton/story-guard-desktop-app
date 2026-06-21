from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backend.app.services import local_llm
from backend.app.services.local_llm import LocalLlmExtractor


class FakeChatLlm:
    def __init__(self, responses: str | list[str]) -> None:
        self.responses = [responses] if isinstance(responses, str) else responses
        self.calls: list[dict] = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return {"choices": [{"message": {"content": self.responses[index]}}]}


class FakeLoadLocalLlmExtractor(LocalLlmExtractor):
    def __init__(self, fake_llm: FakeChatLlm, model_path: Path) -> None:
        super().__init__(model="test-model.gguf", model_dir=model_path.parent)
        self.fake_llm = fake_llm

    def _load_llm(self, model_path: Path):
        return self.fake_llm


def test_local_llm_uses_compact_fact_line_completion(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            """
ENTITY|character|서지안|유리왕관 감시관|서안
ENTITY|place|유리왕관|항로의 궁전|
ISSUE|high|contradiction|왕관 항로 충돌|서지안의 항로 규칙이 상충한다.
END
""".strip(),
            """
REL|서지안|유리왕관|감시|0.82
REL|서지안|유리왕관|감시|0.31
REL|한서윤|유리왕관|예시 환각|0.9
END
""".strip(),
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    payload = FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts("서지안은 유리왕관을 감시했다.")

    assert payload["entities"][0]["name"] == "서지안"
    assert payload["entities"][0]["aliases"] == ["서안"]
    assert len(payload["relations"]) == 1
    assert payload["relations"][0]["confidence"] == 0.82
    assert payload["issues"][0]["title"] == "왕관 항로 충돌"
    assert len(fake_llm.calls) == 2
    assert fake_llm.calls[0]["max_tokens"] <= 900
    assert fake_llm.calls[1]["max_tokens"] <= 700
    assert "response_format" not in fake_llm.calls[0]
    assert "response_format" not in fake_llm.calls[1]
    assert fake_llm.calls[0]["stop"] == ["\nEND", "END"]
    assert fake_llm.calls[1]["stop"] == ["\nEND", "END"]
    entity_prompt = fake_llm.calls[0]["messages"][1]["content"]
    relation_prompt = fake_llm.calls[1]["messages"][1]["content"]
    assert "ENTITY|type|name|summary|aliases" in entity_prompt
    assert "REL|source|target|type|confidence" in relation_prompt
    assert "알려진 엔티티" in relation_prompt
    assert "aliases에는 별칭만" in entity_prompt
    assert "관계 선언 1줄마다 REL 한 줄" in relation_prompt
    assert "REL|<조직명>|<인물명>|소속/조직|0.9" in relation_prompt
    assert "일반 소설 문장만으로 구성되어 있어도" in entity_prompt
    assert "관계표가 없어도" in relation_prompt
    assert "같은 조직 안의 인물 간 관계" in relation_prompt
    assert "협력, 적대, 감시, 명령, 조사, 소유/사용, 비밀 거래" in relation_prompt
    assert "REL|<인물명>|<조직명>|감시/조사|0.78" in relation_prompt
    assert "stream" not in fake_llm.calls[0]
    assert "stream" not in fake_llm.calls[1]


def test_local_llm_prompt_uses_generic_ontology_rules_without_story_specific_names(
    monkeypatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(["ENTITY|place|접견실|회백원 접견실|\nEND", "END"])
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts("접견실 창밖에서 백유라가 웃었다.")

    entity_prompt = fake_llm.calls[0]["messages"][1]["content"]
    entity_instructions = entity_prompt.split("\n원고:", 1)[0]
    assert "대표 공간명 하나만 출력" in entity_prompt
    assert "고유 조직명은 반드시 organization 후보" in entity_prompt
    for story_specific_term in ("접견실", "회백원", "해무상단", "청린 감찰국", "백유라"):
        assert story_specific_term not in entity_instructions


def test_local_llm_collapses_spatial_sentence_fragments_before_persisting(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            """
ENTITY|character|서하|기록관|
ENTITY|item|접견실|접견 공간|
ENTITY|item|접견실 창|창|
ENTITY|item|접견실 창 밖의 문턱을 넘지 않은 채 웃었다|문턱|
END
""".strip(),
            "REL|서하|접견실 창|관찰|0.8\nEND",
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    payload = FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts(
        "서하는 접견실을 보았다. 접견실 창밖에서 백유라가 문턱을 넘지 않은 채 웃었다."
    )

    place_entities = [entity for entity in payload["entities"] if entity["name"] == "접견실"]
    assert len(place_entities) == 1
    assert place_entities[0]["type"] == "place"
    assert not [entity for entity in payload["entities"] if "문턱을 넘지 않은" in entity["name"]]
    assert payload["relations"][0]["target"] == "접견실"


def test_local_llm_normalizes_noisy_item_sentence_fragments(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            """
ENTITY|item|길이의 열쇠|열쇠|
ENTITY|item|백유라가 우산|우산|
ENTITY|item|그리고 등잔|등잔|
ENTITY|item|열|한 글자 노이즈|
END
""".strip(),
            "END",
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    story = """
서하는 봉인함 안에서 흑유리 열쇠를 꺼냈다.
접견실 창밖에서 백유라가 우산을 접었다. 그리고 등잔 유리 안쪽에는 문장이 떠올랐다.
""".strip()
    payload = FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts(story)

    item_names = {entity["name"] for entity in payload["entities"] if entity["type"] == "item"}
    assert "흑유리 열쇠" in item_names
    assert "우산" in item_names
    assert "등잔" in item_names
    assert "길이의 열쇠" not in item_names
    assert "백유라가 우산" not in item_names
    assert "그리고 등잔" not in item_names
    assert "열" not in item_names


def test_local_llm_recovers_named_organizations_for_relation_extraction(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            """
ENTITY|character|서하|기록관|
ENTITY|character|백유라|장부 관리인|
ENTITY|character|류하진|감찰관|
END
""".strip(),
            """
REL|회백원|서하|소속/조직|0.86
REL|해무상단|백유라|소속/조직|0.9
REL|청린 감찰국|류하진|소속/조직|0.88
END
""".strip(),
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    story = """
이서하는 회백원 기록관이었다.
백유라는 해무상단의 장부 관리인이었다.
접견실에는 청린 감찰국의 푸른 제복이 서 있었다. 류하진은 모자를 벗었다.
""".strip()
    payload = FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts(story)

    entity_types = {entity["name"]: entity["type"] for entity in payload["entities"]}
    assert entity_types["회백원"] == "organization"
    assert entity_types["해무상단"] == "organization"
    assert entity_types["청린 감찰국"] == "organization"
    relation_prompt = fake_llm.calls[1]["messages"][1]["content"]
    assert "회백원" in relation_prompt
    assert "해무상단" in relation_prompt
    assert "청린 감찰국" in relation_prompt
    assert {relation["source"] for relation in payload["relations"]} >= {"회백원", "해무상단", "청린 감찰국"}


def test_local_llm_prefers_explicit_story_evidence_over_wrong_membership(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            """
ENTITY|character|서하|기록관|
ENTITY|character|도윤|경비대장|
ENTITY|character|류하진|감찰관|
ENTITY|character|백유라|장부 관리인|
ENTITY|organization|회백원 경비대|경비 조직|
ENTITY|organization|해무상단|상단 조직|
ENTITY|item|열쇠|흑유리 열쇠|
END
""".strip(),
            """
REL|회백원 경비대|서하|소속/조직|0.9
REL|회백원 경비대|도윤|소속/조직|0.8
REL|회백원 경비대|류하진|소속/조직|0.7
REL|회백원 경비대|백유라|소속/조직|0.6
END
""".strip(),
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)
    story = """
이서하는 회백원 지하 서고의 문을 닫았다.
강도윤은 젖은 외투를 털며 계단을 내려왔다. 그는 회백원 경비대장답게 말보다 발소리가 먼저였다.
서하는 봉인함 안에서 흑유리 열쇠를 꺼냈다.
백유라는 해무상단의 장부 관리인이었지만 상단주보다 더 많은 비밀을 알고 있다는 소문을 달고 다녔다.
접견실에는 청린 감찰국의 푸른 제복이 서 있었다. 류하진은 젖은 모자를 벗어 탁자 위에 올렸다.
""".strip()

    payload = FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts(story)

    entity_types = {entity["name"]: entity["type"] for entity in payload["entities"]}
    assert entity_types["이서하"] == "character"
    assert entity_types["강도윤"] == "character"
    assert entity_types["백유라"] == "character"
    assert entity_types["류하진"] == "character"
    assert entity_types["흑유리 열쇠"] == "item"
    assert entity_types["청린 감찰국"] == "organization"

    membership_pairs = {
        (relation["source"], relation["target"])
        for relation in payload["relations"]
        if relation["type"] == "소속/조직"
    }
    assert ("해무상단", "백유라") in membership_pairs
    assert ("청린 감찰국", "류하진") in membership_pairs
    assert ("회백원 경비대", "강도윤") in membership_pairs
    assert ("회백원 경비대", "백유라") not in membership_pairs
    assert ("회백원 경비대", "류하진") not in membership_pairs


def test_local_llm_drops_unsupported_organization_item_usage(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            """
ENTITY|organization|회백원|기록 조직|
ENTITY|item|불빛|등화의 빛|
ENTITY|item|항로 장부|항로 기록|
END
""".strip(),
            """
REL|회백원|불빛|소유/사용|0.8
REL|회백원|항로 장부|소유/사용|0.8
END
""".strip(),
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)
    story = """
회백원 기록관들은 그 불빛을 함부로 건드리지 않았다.
항로 장부는 회백원이 바다 위의 길과 배신자를 함께 적어 온 기록이었다.
""".strip()

    payload = FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts(story)

    relation_pairs = {(relation["source"], relation["target"]) for relation in payload["relations"]}
    assert ("회백원", "불빛") not in relation_pairs
    assert ("회백원", "항로 장부") in relation_pairs


def test_local_llm_drops_unsupported_issue_without_conflict_language(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            """
ENTITY|character|점순|마을 소녀|
ISSUE|high|world_rule|동백꽃 점순네 수탉 장면|점순네 수탉이 우리 수탉을 쪼았다.
ISSUE|medium|contradiction|점순이가 닭을 패하는 중|점순이가 닭을 패하는 장면이다.
END
""".strip(),
            "END",
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    payload = FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts(
        "점순네 수탉이 우리 수탉을 쪼았다. 점순이는 감자를 내밀었다."
    )

    assert payload["issues"] == []


def test_local_llm_drops_unsupported_dedicated_continuity_issue(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        """
ISSUE|medium|contradiction|점순이가 닭을 패하는 중|점순이가 닭을 패하는 장면이다.
END
""".strip()
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    issues = FakeLoadLocalLlmExtractor(fake_llm, model_path).detect_continuity_issues(
        "점순네 수탉이 우리 수탉을 쪼았다. 점순이는 감자를 내밀었다.",
        context="",
        known_entity_names=["점순", "우리 수탉", "점순네 수탉"],
    )

    assert issues == []


def test_local_llm_drops_scene_conflict_without_continuity_context(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        """
ISSUE|high|world_rule|점순네 수탉과 우리 수탉의 충돌|점순네 수탉이 우리 수탉을 해내는 장면이다.
END
""".strip()
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    issues = FakeLoadLocalLlmExtractor(fake_llm, model_path).detect_continuity_issues(
        "점순네 수탉이 우리 수탉을 쪼았다. 점순이는 감자를 내밀었다.",
        context="기존 엔티티: character:나, character:점순",
        known_entity_names=["점순", "우리 수탉", "점순네 수탉"],
    )

    assert issues == []


def test_local_llm_keeps_common_item_headword_as_canonical_name() -> None:
    payload = local_llm.sanitize_story_payload(
        {
            "entities": [
                {"type": "item", "name": "감자", "summary": "먹을거리", "aliases": []},
                {"type": "item", "name": "나귀", "summary": "짐승", "aliases": []},
            ],
            "relations": [],
            "issues": [],
        },
        story_text="점순이는 굵은 감자를 내밀었다. 허 생원은 대단한 나귀를 몰았다.",
    )

    entity_names = {entity["name"] for entity in payload["entities"]}
    assert "감자" in entity_names
    assert "나귀" in entity_names
    assert "굵은 감자" not in entity_names
    assert "대단한 나귀" not in entity_names


def test_local_llm_drops_weak_organizations_body_part_items_and_invalid_ownership_sources() -> None:
    payload = local_llm.sanitize_story_payload(
        {
            "entities": [
                {"type": "character", "name": "나", "summary": "화자", "aliases": ["킥", "aliases", "고추장"]},
                {"type": "character", "name": "점순", "summary": "마을 소녀", "aliases": []},
                {"type": "item", "name": "우리 수탉", "summary": "화자의 닭", "aliases": []},
                {"type": "item", "name": "점순네 수탉", "summary": "점순네 닭", "aliases": []},
                {"type": "place", "name": "울타리", "summary": "장소", "aliases": []},
                {"type": "organization", "name": "거지반", "summary": "잘못 잡은 조직", "aliases": []},
                {"type": "organization", "name": "소나무 삭정", "summary": "잘못 잡은 조직", "aliases": []},
                {"type": "item", "name": "붉은 선혈", "summary": "몸 상태", "aliases": []},
                {"type": "item", "name": "않은 면두", "summary": "닭 신체 부위", "aliases": ["면두"]},
                {"type": "item", "name": "푸드득하고 모가지", "summary": "닭 신체 부위", "aliases": ["모가지"]},
                {"type": "item", "name": "닭도 고추장", "summary": "먹이 묘사", "aliases": ["고추장"]},
            ],
            "relations": [
                {"source": "나", "target": "우리 수탉", "type": "소유/사용", "confidence": 0.8},
                {"source": "점순", "target": "점순네 수탉", "type": "소유/사용", "confidence": 0.8},
                {"source": "점순", "target": "우리 수탉", "type": "소유/사용", "confidence": 0.8},
                {"source": "나", "target": "점순네 수탉", "type": "소유/사용", "confidence": 0.8},
                {"source": "울타리", "target": "우리 수탉", "type": "소유/사용", "confidence": 0.8},
                {"source": "점순네 수탉", "target": "우리 수탉", "type": "소유/사용", "confidence": 0.8},
            ],
            "issues": [],
        },
        story_text=(
            "나는 울타리 옆에서 우리 수탉을 보았다. 점순은 점순네 수탉을 불렀다. "
            "붉은 선혈이 떨어지고 모가지를 쪼았다. 닭도 고추장을 먹었다."
        ),
    )

    entity_names = {entity["name"] for entity in payload["entities"]}
    relation_tuples = {
        (relation["source"], relation["target"], relation["type"])
        for relation in payload["relations"]
    }
    assert "거지반" not in entity_names
    assert "소나무 삭정" not in entity_names
    assert "붉은 선혈" not in entity_names
    assert "않은 면두" not in entity_names
    assert "푸드득하고 모가지" not in entity_names
    assert "닭도 고추장" not in entity_names
    narrator = next(entity for entity in payload["entities"] if entity["name"] == "나")
    assert "킥" not in narrator["aliases"]
    assert "aliases" not in narrator["aliases"]
    assert "고추장" not in narrator["aliases"]
    assert ("나", "우리 수탉", "소유/사용") in relation_tuples
    assert ("점순", "점순네 수탉", "소유/사용") in relation_tuples
    assert ("점순", "우리 수탉", "소유/사용") not in relation_tuples
    assert ("나", "점순네 수탉", "소유/사용") not in relation_tuples
    assert ("울타리", "우리 수탉", "소유/사용") not in relation_tuples
    assert ("점순네 수탉", "우리 수탉", "소유/사용") not in relation_tuples


def test_local_llm_merges_classic_title_aliases_and_recovers_family_relations(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            """
ENTITY|character|홍길동|서자 영웅|길동, aliases:길동
ENTITY|character|길동|홍길동 별칭|
ENTITY|character|승상|홍길동의 부친|
ENTITY|character|부인|홍씨 집안 부인|aliases:부인
ENTITY|character|춘섬|길동의 생모|
ENTITY|organization|백야단|원문에 없는 환각 조직|
ENTITY|item|모자|착용 물건|
ENTITY|item|검|무기|
END
""".strip(),
            """
REL|승상|길동|관계|0.9
REL|길동|홍길동|관계/관계|0.8
REL|길동|부인|관계|0.8
REL|길동|부인|소속/조직|0.9
REL|춘섬|길동|관계|0.8
REL|홍길동|검|소유/사용|0.78
END
""".strip(),
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)
    story = """
조선국 세종대왕 즉위 십오년에 홍회문 밖에 한 재상이 있으되, 성은 홍이요, 명은 문이니.
이조판서로 좌의정을 하게 하시니, 승상이 집에 돌아와 부인에게 말하였다.
춘섬이 태기 있어 기남자를 낳으니, 삼일 후에 승상이 들어와 보시고 이름을 길동이라 하니라.
길동은 어려서 부친을 부친이라 못하고 형을 형이라 못하여 한탄하였다.
길동이 대감께 아뢰기를 소인은 대감의 정기를 타 당당한 남자가 되었사오나 아비를 아비라 부르지 못하옵니다.
모친은 소자와 전생연분으로 차생에 모자 되오니 이별을 슬퍼하지 말라 하였다.
홍길동은 검을 들고 문밖으로 나섰다.
""".strip()

    payload = FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts(story)

    entities = {entity["name"]: entity for entity in payload["entities"]}
    assert "홍길동" in entities
    assert "홍문" in entities
    assert "춘섬" in entities
    assert "길동" not in entities
    assert "승상" not in entities
    assert "우승상" not in entities
    assert "무아부인" not in entities
    assert "모자" not in entities
    assert "백야단" not in entities
    assert "길동" in entities["홍길동"]["aliases"]
    assert {"승상", "대감", "재상"} <= set(entities["홍문"]["aliases"])
    assert all(not alias.startswith("aliases:") for entity in entities.values() for alias in entity["aliases"])

    relation_tuples = {
        (relation["source"], relation["target"], relation["type"])
        for relation in payload["relations"]
    }
    assert ("홍문", "홍길동", "부자/부친") in relation_tuples
    assert ("춘섬", "홍길동", "모자/생모") in relation_tuples
    assert ("홍길동", "홍길동", "관계/관계") not in relation_tuples
    assert ("홍길동", "부인", "관계") not in relation_tuples
    assert ("홍길동", "부인", "소속/조직") not in relation_tuples
    assert ("홍길동", "검", "소유/사용") in relation_tuples


def test_local_llm_bounds_prompt_size_and_includes_previous_context(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        [
            "ENTITY|character|서지안|감시관|\nEND",
            "REL|서지안|이서하|조사|0.8\nEND",
        ]
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts(
        "가" * 12000,
        context="기존 엔티티: 이서하, 강도윤\n" + ("이전 관계. " * 1000),
        known_entity_names=["이서하", "강도윤"],
    )

    entity_prompt = fake_llm.calls[0]["messages"][1]["content"]
    relation_prompt = fake_llm.calls[1]["messages"][1]["content"]

    assert len(entity_prompt) <= 5200
    assert len(relation_prompt) <= 5200
    assert "기존 분석 요약" in entity_prompt
    assert "이서하" in relation_prompt
    assert "강도윤" in relation_prompt


def test_local_llm_dedicated_continuity_issue_detection_prompt(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        """
ISSUE|high|world_rule|푸른 등화 혈통 규칙 충돌|초반 규칙과 후반 보고서가 다르다.
END
""".strip()
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    issues = FakeLoadLocalLlmExtractor(fake_llm, model_path).detect_continuity_issues(
        "5화. 보고서는 푸른 등화가 피와 무관하다고 했다.",
        context="기존 엔티티: rule:푸른 등화(회백원의 피가 필요)",
        known_entity_names=["푸른 등화"],
    )

    prompt = fake_llm.calls[0]["messages"][1]["content"]
    assert issues[0]["title"] == "푸른 등화 혈통 규칙 충돌"
    assert "설정 붕괴 후보만" in prompt
    assert "기존 분석 요약" in prompt
    assert "ENTITY|" not in prompt
    assert fake_llm.calls[0]["max_tokens"] <= 500


def test_local_llm_reports_friendly_error_for_empty_fact_lines(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm("분석 결과를 만들 수 없습니다.")
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    with pytest.raises(RuntimeError) as error:
        FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts("서지안은 유리왕관을 감시했다.")

    assert "분석 결과 형식을 완성하지 못했습니다" in str(error.value)
    assert "Expecting" not in str(error.value)


def test_local_llm_reports_friendly_error_for_malformed_json(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    fake_llm = FakeChatLlm(
        """
{
  "entities": [
    {"type": "character", "name": "서지안", "summary": "감시관", "aliases": []}
    {"type": "place", "name": "유리왕관", "summary": "항로", "aliases": []}
  ],
  "relations": [],
  "issues": []
}
""".strip()
    )
    monkeypatch.setattr(local_llm, "llama_cpp_available", lambda: True)

    with pytest.raises(RuntimeError) as error:
        FakeLoadLocalLlmExtractor(fake_llm, model_path).extract_story_facts("서지안은 유리왕관을 감시했다.")

    assert "분석 결과 형식을 완성하지 못했습니다" in str(error.value)
    assert "Expecting" not in str(error.value)


def test_local_llm_loader_enables_gpu_offload(monkeypatch, tmp_path: Path) -> None:
    model_path = tmp_path / "test-model.gguf"
    model_path.write_bytes(b"placeholder")
    captured: dict = {}

    class FakeLlama:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(LocalLlmExtractor, "_llm_cache", {})
    monkeypatch.setattr(local_llm, "llama_gpu_layer_count", lambda: -1)
    monkeypatch.setitem(sys.modules, "llama_cpp", SimpleNamespace(Llama=FakeLlama))

    loaded = LocalLlmExtractor(model="test-model.gguf", model_dir=tmp_path)._load_llm(model_path)

    assert isinstance(loaded, FakeLlama)
    assert captured["n_gpu_layers"] == -1


def test_llm_thread_count_defaults_to_small_cpu_budget(monkeypatch) -> None:
    monkeypatch.delenv("STORY_GUARD_LLM_THREADS", raising=False)
    monkeypatch.setattr(local_llm.os, "cpu_count", lambda: 12)

    assert local_llm.llm_thread_count() == 1


def test_llm_thread_count_caps_user_override(monkeypatch) -> None:
    monkeypatch.setenv("STORY_GUARD_LLM_THREADS", "16")
    monkeypatch.setattr(local_llm.os, "cpu_count", lambda: 12)

    assert local_llm.llm_thread_count() == 4


def test_llm_thread_count_uses_safe_value_for_invalid_override(monkeypatch) -> None:
    monkeypatch.setenv("STORY_GUARD_LLM_THREADS", "fast")
    monkeypatch.setattr(local_llm.os, "cpu_count", lambda: 12)

    assert local_llm.llm_thread_count() == 1
