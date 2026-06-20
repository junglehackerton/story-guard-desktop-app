from pathlib import Path

import pytest

from backend.app.database import Database
from backend.app.models import AnalysisStatus
from backend.app.pipeline.analyzer import ANALYSIS_PROMPT_VERSION, StoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.parser import read_document, split_chunks


class DisabledLlmExtractor:
    def enabled(self) -> bool:
        return False

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
        raise AssertionError("disabled LLM must not be called")


class FakeLlmExtractor:
    def enabled(self) -> bool:
        return True

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
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


class ProgressAwareLlmExtractor(FakeLlmExtractor):
    def __init__(self, repository: StoryRepository, project_id: int) -> None:
        self.repository = repository
        self.project_id = project_id

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
        job = self.repository.latest_analysis_job(self.project_id)

        assert job is not None
        assert job.status == "running"
        assert job.current_step == "extract"
        assert 20 <= job.progress < 60

        return super().extract_story_facts(text, context, known_entity_names)


class CancellingLlmExtractor(FakeLlmExtractor):
    def __init__(self, repository: StoryRepository, project_id: int) -> None:
        self.repository = repository
        self.project_id = project_id

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
        self.repository.cancel_analysis(self.project_id)
        return super().extract_story_facts(text, context, known_entity_names)


class SparseLlmExtractor:
    def enabled(self) -> bool:
        return True

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
        return {"entities": [], "relations": [], "issues": []}


class CacheOnlyLlmExtractor:
    model = "cache-only-model.gguf"

    def enabled(self) -> bool:
        return True

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
        raise AssertionError("cached analysis should be sanitized without calling the LLM")


class RecordingLlmExtractor(FakeLlmExtractor):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enabled(self) -> bool:
        return True

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
        self.calls.append(
            {
                "text": text,
                "context": context,
                "known_entity_names": known_entity_names or [],
            }
        )
        return super().extract_story_facts(text, context, known_entity_names)


class IncrementalLlmExtractor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enabled(self) -> bool:
        return True

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
        self.calls.append(
            {
                "text": text,
                "context": context,
                "known_entity_names": known_entity_names or [],
            }
        )
        index = len(self.calls)
        name = ["이서하", "강도윤", "류하진"][index - 1]
        payload = {
            "entities": [
                {"type": "character", "name": name, "summary": f"{index}화 등장인물", "aliases": []},
            ],
            "relations": [],
            "issues": [],
        }
        if index > 1:
            payload["relations"].append(
                {"source": "이서하", "target": name, "type": "동행/협력", "confidence": 0.8}
            )
        return payload


class ChapterAwareLlmExtractor:
    CHAPTER_ENTITIES = {
        "1화": "이서하",
        "2화": "강도윤",
        "3화": "류하진",
        "4화": "백유라",
        "5화": "오문석",
        "6화": "마리안",
    }

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enabled(self) -> bool:
        return True

    def extract_story_facts(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> dict:
        self.calls.append(
            {
                "text": text,
                "context": context,
                "known_entity_names": known_entity_names or [],
            }
        )
        name = next((entity for marker, entity in self.CHAPTER_ENTITIES.items() if marker in text), "이서하")
        payload = {
            "entities": [
                {"type": "character", "name": name, "summary": "회차 등장인물", "aliases": []},
            ],
            "relations": [],
            "issues": [],
        }
        if name != "이서하":
            payload["relations"].append(
                {"source": "이서하", "target": name, "type": "서사/연결", "confidence": 0.8}
            )
        return payload


class ContinuityDetectingLlmExtractor(ChapterAwareLlmExtractor):
    def __init__(self) -> None:
        super().__init__()
        self.issue_detection_calls: list[dict] = []

    def detect_continuity_issues(
        self,
        text: str,
        context: str = "",
        known_entity_names: list[str] | None = None,
    ) -> list[dict]:
        self.issue_detection_calls.append(
            {
                "text": text,
                "context": context,
                "known_entity_names": known_entity_names or [],
            }
        )
        return [
            {
                "severity": "high",
                "category": "world_rule",
                "title": "푸른 등화 혈통 규칙 충돌",
                "description": "초반에는 회백원의 피가 필요했지만 후반 보고서는 피와 무관하다고 말한다.",
            }
        ]


def add_story_document(
    repository: StoryRepository,
    project_id: int,
    tmp_path: Path,
    content: str,
    index: int = 0,
) -> None:
    story_path = tmp_path / f"story-{index:02d}.txt"
    story_path.write_text(content, encoding="utf-8")
    parsed, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project_id,
        path=story_path,
        title=f"story-{index:02d}",
        file_format=file_format,
        content_hash=digest,
        content=parsed,
        chapter_index=index,
    )
    repository.replace_chunks(project_id, document.id, split_chunks(parsed))


def add_story(repository: StoryRepository, project_id: int, tmp_path: Path, content: str) -> None:
    add_story_document(repository, project_id, tmp_path, content)


def add_story_series(repository: StoryRepository, project_id: int, tmp_path: Path, count: int) -> None:
    for index in range(count):
        add_story_document(
            repository,
            project_id,
            tmp_path,
            f"{index + 1}화. 한서윤은 검은 열쇠를 들고 흑월성에 갔다.",
            index,
        )


def test_analyzer_requires_local_llm(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("LLM 필수 작품")
    add_story(repository, project.id, tmp_path, "한서윤은 검은 열쇠를 들고 흑월성에 갔다.")

    with pytest.raises(RuntimeError, match="로컬 LLM 모델"):
        StoryAnalyzer(repository, llm=DisabledLlmExtractor()).analyze_project(project.id)


def test_analyzer_rejects_project_that_is_already_running(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("중복 분석 방지 작품")
    add_story(repository, project.id, tmp_path, "한서윤은 검은 열쇠를 들고 흑월성에 갔다.")
    existing = repository.create_job(
        project.id,
        AnalysisStatus.running,
        "이미 LLM 분석 중",
        current_step="extract",
        progress=42,
    )

    with pytest.raises(RuntimeError, match="이미 분석"):
        StoryAnalyzer(repository, llm=FakeLlmExtractor()).analyze_project(project.id)

    assert repository.running_analysis_job(project.id).id == existing.id


def test_analyzer_persists_only_llm_payload(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("LLM 작품")
    add_story_series(repository, project.id, tmp_path, 5)

    result = StoryAnalyzer(repository, llm=FakeLlmExtractor()).analyze_project(project.id)
    graph = repository.graph(project.id)

    assert result.entity_count == 3
    assert {entity.name for entity in graph.entities} == {"한서윤", "검은 열쇠", "흑월성"}
    assert {relation.type for relation in graph.relations} == {"소유/사용", "등장 장소"}
    assert graph.issues[0].title == "LLM 설정 충돌"


def test_analyzer_processes_documents_sequentially_with_previous_context(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("회차 누적 작품")
    add_story_document(repository, project.id, tmp_path, "1화. 이서하는 회백원 서고를 지켰다.", 0)
    add_story_document(repository, project.id, tmp_path, "2화. 강도윤은 이서하를 호위했다.", 1)
    add_story_document(repository, project.id, tmp_path, "3화. 류하진은 두 사람을 조사했다.", 2)
    llm = IncrementalLlmExtractor()

    StoryAnalyzer(repository, llm=llm).analyze_project(project.id)
    graph = repository.graph(project.id)

    assert len(llm.calls) == 3
    assert "1화" in llm.calls[0]["text"]
    assert "2화" not in llm.calls[0]["text"]
    assert "2화" in llm.calls[1]["text"]
    assert "1화" not in llm.calls[1]["text"]
    assert "기존 엔티티" in llm.calls[1]["context"]
    assert "이서하" in llm.calls[1]["context"]
    assert "이서하" in llm.calls[2]["known_entity_names"]
    assert {entity.name for entity in graph.entities} == {"이서하", "강도윤", "류하진", "회백원"}
    assert {relation.type for relation in graph.relations} == {"동행/협력"}


def test_analyzer_splits_long_document_before_local_llm_call(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("긴 회차 작품")
    long_episode = "\n".join(f"{index}번째 문단. 이서하는 유리항의 비밀을 기록했다." for index in range(260))
    add_story_document(repository, project.id, tmp_path, long_episode, 0)
    llm = RecordingLlmExtractor()

    StoryAnalyzer(repository, llm=llm).analyze_project(project.id)

    assert len(llm.calls) > 1
    assert all(len(call["text"]) <= 3200 for call in llm.calls)


def test_analyzer_reuses_cached_document_analysis_when_chapters_are_added(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("증분 분석 작품")
    for index in range(3):
        add_story_document(
            repository,
            project.id,
            tmp_path,
            f"{index + 1}화. {ChapterAwareLlmExtractor.CHAPTER_ENTITIES[f'{index + 1}화']}가 유리항에 등장했다.",
            index,
        )
    first_llm = ChapterAwareLlmExtractor()
    StoryAnalyzer(repository, llm=first_llm).analyze_project(project.id)

    for index in range(3, 6):
        add_story_document(
            repository,
            project.id,
            tmp_path,
            f"{index + 1}화. {ChapterAwareLlmExtractor.CHAPTER_ENTITIES[f'{index + 1}화']}가 새 단서를 가져왔다.",
            index,
        )
    second_llm = ChapterAwareLlmExtractor()

    StoryAnalyzer(repository, llm=second_llm).analyze_project(project.id)
    graph = repository.graph(project.id)
    documents = repository.list_documents(project.id)

    assert len(first_llm.calls) == 3
    assert len(second_llm.calls) == 3
    assert all("1화" not in call["text"] and "2화" not in call["text"] and "3화" not in call["text"] for call in second_llm.calls)
    assert "4화" in second_llm.calls[0]["text"]
    assert "이서하" in second_llm.calls[0]["context"]
    assert "이서하" in second_llm.calls[0]["known_entity_names"]
    assert {entity.name for entity in graph.entities} == {"이서하", "강도윤", "류하진", "백유라", "오문석", "마리안"}
    assert [document.analysis_status for document in documents] == ["analyzed"] * 6
    assert all(document.analysis_entity_count == 1 for document in documents)


def test_analyzer_sanitizes_cached_episode_payload_before_projecting_graph(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("캐시 정규화 작품")
    story = """
이서하는 회백원 지하 서고의 문을 닫았다.
강도윤은 회백원 경비대장답게 계단을 내려왔다.
백유라는 해무상단의 장부 관리인이었다.
접견실에는 청린 감찰국의 푸른 제복이 서 있었다. 류하진은 젖은 모자를 벗었다.
접견실 창밖에서 백유라가 문턱을 넘지 않은 채 웃었다.
""".strip()
    story_path = tmp_path / "episode-01.txt"
    story_path.write_text(story, encoding="utf-8")
    parsed, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project.id,
        path=story_path,
        title="episode-01",
        file_format=file_format,
        content_hash=digest,
        content=parsed,
        chapter_index=0,
    )
    repository.replace_chunks(project.id, document.id, split_chunks(parsed))
    bad_payload = {
        "entities": [
            {"type": "character", "name": "서하", "summary": "기록관", "aliases": []},
            {"type": "item", "name": "접견실", "summary": "접견 공간", "aliases": []},
            {"type": "item", "name": "접견실 창", "summary": "창", "aliases": []},
            {"type": "item", "name": "접견실 창 밖의 문턱", "summary": "문턱", "aliases": []},
            {"type": "item", "name": "접견실 창 밖의 문턱을 넘지 않은 채 웃었다", "summary": "문턱", "aliases": []},
        ],
        "relations": [
            {"source": "서하", "target": "접견실 창", "type": "관찰", "confidence": 0.8},
            {"source": "접견실 창", "target": "접견실 창 밖의 문턱", "type": "관계", "confidence": 0.7},
        ],
        "issues": [],
    }
    repository.replace_episode_analysis(
        project.id,
        document.id,
        digest,
        bad_payload,
        model_name=CacheOnlyLlmExtractor.model,
        prompt_version=ANALYSIS_PROMPT_VERSION,
    )

    StoryAnalyzer(repository, llm=CacheOnlyLlmExtractor()).analyze_project(project.id)
    graph = repository.graph(project.id)

    entity_types = {entity.name: entity.type for entity in graph.entities}
    assert entity_types["접견실"] == "place"
    assert "접견실 창" not in entity_types
    assert "접견실 창 밖의 문턱" not in entity_types
    assert not [name for name in entity_types if "넘지 않은" in name]
    assert entity_types["회백원"] == "organization"
    assert entity_types["회백원 경비대"] == "organization"
    assert entity_types["해무상단"] == "organization"
    assert entity_types["청린 감찰국"] == "organization"
    assert graph.relations[0].target_entity_id == next(entity.id for entity in graph.entities if entity.name == "접견실")


def test_analyzer_runs_dedicated_continuity_issue_detection_after_five_documents(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("설정 붕괴 점검 작품")
    for index in range(6):
        add_story_document(
            repository,
            project.id,
            tmp_path,
            f"{index + 1}화. 푸른 등화와 흑유리 열쇠에 관한 새 장면이 이어진다.",
            index,
        )
    llm = ContinuityDetectingLlmExtractor()

    result = StoryAnalyzer(repository, llm=llm).analyze_project(project.id)
    graph = repository.graph(project.id)

    assert len(llm.issue_detection_calls) == 1
    assert "기존 엔티티" in llm.issue_detection_calls[0]["context"]
    assert "푸른 등화" in graph.issues[0].title
    assert result.issue_count == 1


def test_analyzer_defers_continuity_issues_until_five_documents(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("초반 연재 작품")
    add_story_series(repository, project.id, tmp_path, 4)

    result = StoryAnalyzer(repository, llm=FakeLlmExtractor()).analyze_project(project.id)
    graph = repository.graph(project.id)

    assert result.entity_count == 3
    assert result.relation_count == 2
    assert result.issue_count == 0
    assert graph.issues == []


def test_analyzer_updates_progress_while_llm_is_extracting(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("진행 상태 작품")
    add_story(repository, project.id, tmp_path, "한서윤은 검은 열쇠를 들고 흑월성에 갔다.")

    StoryAnalyzer(
        repository,
        llm=ProgressAwareLlmExtractor(repository, project.id),
    ).analyze_project(project.id)
    job = repository.latest_analysis_job(project.id)

    assert job is not None
    assert job.status == "completed"
    assert job.current_step == "completed"
    assert job.progress == 100


def test_analyzer_cancels_without_persisting_llm_payload(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("취소 작품")
    add_story(repository, project.id, tmp_path, "한서윤은 검은 열쇠를 들고 흑월성에 갔다.")

    with pytest.raises(RuntimeError, match="취소"):
        StoryAnalyzer(
            repository,
            llm=CancellingLlmExtractor(repository, project.id),
        ).analyze_project(project.id)

    job = repository.latest_analysis_job(project.id)
    graph = repository.graph(project.id)

    assert job is not None
    assert job.status == "cancelled"
    assert job.current_step == "cancelled"
    assert graph.entities == []
    assert graph.relations == []
    assert graph.issues == []


def test_analyzer_rejects_empty_llm_payload(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("빈 분석 작품")
    add_story(repository, project.id, tmp_path, "아무 설정도 추출되지 않는 원고")

    with pytest.raises(RuntimeError, match="분석 결과가 비어"):
        StoryAnalyzer(repository, llm=SparseLlmExtractor()).analyze_project(project.id)


def test_analyzer_sends_explicit_story_declarations_to_local_llm(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("LLM 명시 선언 작품")
    llm = RecordingLlmExtractor()
    add_story(
        repository,
        project.id,
        tmp_path,
        """
인물: 윤하린, 도겸
장소: 백야성
조직: 백야단
사건: 지하 서고 봉쇄
소속: 윤하린 -> 백야단
본부: 백야단 -> 백야성
관할: 백야단 -> 지하 서고 봉쇄
""".strip(),
    )

    result = StoryAnalyzer(repository, llm=llm).analyze_project(project.id)
    graph = repository.graph(project.id)

    assert len(llm.calls) == 1
    assert "소속: 윤하린 -> 백야단" in llm.calls[0]["text"]
    assert result.entity_count == 3
    assert {entity.name for entity in graph.entities} == {"한서윤", "검은 열쇠", "흑월성"}
