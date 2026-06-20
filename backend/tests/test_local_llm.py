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
    assert "REL|백야단|한서윤|소속/조직|0.9" in relation_prompt
    assert "일반 소설 문장만으로 구성되어 있어도" in entity_prompt
    assert "관계표가 없어도" in relation_prompt
    assert "같은 조직 안의 인물 간 관계" in relation_prompt
    assert "협력, 적대, 감시, 명령, 조사, 소유/사용, 비밀 거래" in relation_prompt
    assert "REL|백무진|은하 밀수조합|비밀/거래|0.86" in relation_prompt
    assert "stream" not in fake_llm.calls[0]
    assert "stream" not in fake_llm.calls[1]


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
