from pathlib import Path

import pytest

from backend.app.database import Database
from backend.app.pipeline.analyzer import StoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.parser import read_document, split_chunks


class DisabledLlmExtractor:
    def enabled(self) -> bool:
        return False

    def extract_story_facts(self, text: str) -> dict:
        raise AssertionError("disabled LLM must not be called")


class FakeLlmExtractor:
    def enabled(self) -> bool:
        return True

    def extract_story_facts(self, text: str) -> dict:
        return {
            "entities": [
                {"type": "character", "name": "한서윤", "summary": "주인공", "aliases": ["서윤"]},
                {"type": "item", "name": "검은 열쇠", "summary": "봉인을 여는 물건", "aliases": []},
                {"type": "place", "name": "흑월성", "summary": "봉인된 성", "aliases": []},
            ],
            "relations": [
                {"source": "한서윤", "target": "검은 열쇠", "type": "owns", "confidence": 0.8},
                {"source": "서윤", "target": "흑월성", "type": "visited", "confidence": 0.7},
            ],
            "issues": [
                {
                    "severity": "high",
                    "category": "contradiction",
                    "title": "LLM 설정 충돌",
                    "description": "초반과 후반의 인물 지식이 다릅니다.",
                }
            ],
        }


class SparseLlmExtractor:
    def enabled(self) -> bool:
        return True

    def extract_story_facts(self, text: str) -> dict:
        return {"entities": [], "relations": [], "issues": []}


def add_story(repository: StoryRepository, project_id: int, tmp_path: Path, content: str) -> None:
    story_path = tmp_path / "story.txt"
    story_path.write_text(content, encoding="utf-8")
    parsed, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project_id,
        path=story_path,
        title="story",
        file_format=file_format,
        content_hash=digest,
        content=parsed,
    )
    repository.replace_chunks(project_id, document.id, split_chunks(parsed))


def test_analyzer_requires_local_llm(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("LLM 필수 작품")
    add_story(repository, project.id, tmp_path, "한서윤은 검은 열쇠를 들고 흑월성에 갔다.")

    with pytest.raises(RuntimeError, match="로컬 LLM 모델"):
        StoryAnalyzer(repository, llm=DisabledLlmExtractor()).analyze_project(project.id)


def test_analyzer_persists_only_llm_payload(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("LLM 작품")
    add_story(repository, project.id, tmp_path, "한서윤은 검은 열쇠를 들고 흑월성에 갔다.")

    result = StoryAnalyzer(repository, llm=FakeLlmExtractor()).analyze_project(project.id)
    graph = repository.graph(project.id)

    assert result.entity_count == 3
    assert {entity.name for entity in graph.entities} == {"한서윤", "검은 열쇠", "흑월성"}
    assert {relation.type for relation in graph.relations} == {"소유/사용", "등장 장소"}
    assert graph.issues[0].title == "LLM 설정 충돌"


def test_analyzer_rejects_empty_llm_payload(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("빈 분석 작품")
    add_story(repository, project.id, tmp_path, "아무 설정도 추출되지 않는 원고")

    with pytest.raises(RuntimeError, match="분석 결과가 비어"):
        StoryAnalyzer(repository, llm=SparseLlmExtractor()).analyze_project(project.id)
