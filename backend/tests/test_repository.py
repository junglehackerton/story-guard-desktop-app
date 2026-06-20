from pathlib import Path

from backend.app.database import Database
from backend.app.models import AnalysisStatus
from backend.app.repository import StoryRepository, normalize_relation_type


def test_issue_status_persists(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("테스트 작품")
    issue = repository.add_issue(
        project_id=project.id,
        severity="high",
        category="contradiction",
        title="설정 충돌 후보",
        description="초반과 후반 설정이 다릅니다.",
        evidence_chunk_ids=[1],
    )

    updated = repository.update_issue_status(issue.id, "accepted")
    graph = repository.graph(project.id)

    assert updated.status == "accepted"
    assert graph.issues[0].status == "accepted"


def test_relation_normalization_treats_organization_scope_as_membership() -> None:
    assert normalize_relation_type("관할") == "소속/조직"
    assert normalize_relation_type("본부/거점") == "소속/조직"
    assert normalize_relation_type("산하 부대") == "소속/조직"


def test_cancel_running_analysis_marks_job_and_clears_generated_graph(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("취소 테스트")
    job = repository.create_job(
        project.id,
        AnalysisStatus.running,
        "LLM 분석 중",
        current_step="extract",
        progress=42,
    )
    entity = repository.upsert_entity(
        project_id=project.id,
        entity_type="character",
        name="한서윤",
        aliases=[],
        summary="생성 중인 인물",
        first_seen_document_id=None,
    )
    repository.add_issue(
        project_id=project.id,
        severity="medium",
        category="contradiction",
        title="생성 중인 이슈",
        description="취소하면 삭제되어야 한다.",
        evidence_chunk_ids=[],
    )

    cancelled = repository.cancel_analysis(project.id)
    graph = repository.graph(project.id)

    assert cancelled.id == job.id
    assert cancelled.status == "cancelled"
    assert cancelled.current_step == "cancelled"
    assert cancelled.progress == 100
    assert entity.name not in {item.name for item in graph.entities}
    assert graph.entities == []
    assert graph.relations == []
    assert graph.issues == []


def test_cancel_running_analysis_marks_all_running_jobs_cancelled(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("중복 실행 취소 테스트")
    first = repository.create_job(
        project.id,
        AnalysisStatus.running,
        "이전 LLM 분석 중",
        current_step="extract",
        progress=42,
    )
    latest = repository.create_job(
        project.id,
        AnalysisStatus.running,
        "새 LLM 분석 중",
        current_step="extract",
        progress=42,
    )

    cancelled = repository.cancel_analysis(project.id)

    assert cancelled.id == latest.id
    assert repository.get_job(first.id).status == "cancelled"
    assert repository.get_job(latest.id).status == "cancelled"


def test_running_analysis_job_returns_latest_running_job(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("실행 중 조회 테스트")
    repository.create_job(project.id, AnalysisStatus.failed, "이전 실패")
    first_running = repository.create_job(project.id, AnalysisStatus.running, "첫 실행")
    latest_running = repository.create_job(project.id, AnalysisStatus.running, "두 번째 실행")

    running = repository.running_analysis_job(project.id)

    assert running is not None
    assert running.id == latest_running.id
    repository.cancel_analysis(project.id)
    assert repository.running_analysis_job(project.id) is None
    assert repository.get_job(first_running.id).status == "cancelled"


def test_mark_running_jobs_interrupted_closes_stale_jobs(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("잔류 작업 정리 테스트")
    stale = repository.create_job(project.id, AnalysisStatus.running, "이전 실행 잔류")

    changed = repository.mark_running_jobs_interrupted()

    job = repository.get_job(stale.id)
    assert changed == 1
    assert job.status == "failed"
    assert job.current_step == "failed"
    assert "이전 실행" in job.message


def test_episode_analysis_status_range_graph_and_relation_changes(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("회차 범위 테스트")
    first = repository.add_document(
        project.id,
        tmp_path / "episode-01.md",
        "1화",
        "md",
        "hash-1",
        "이서하는 강도윤과 동행했다.",
        chapter_index=0,
    )
    second = repository.add_document(
        project.id,
        tmp_path / "episode-02.md",
        "2화",
        "md",
        "hash-2",
        "이서하는 강도윤을 의심했다.",
        chapter_index=1,
    )
    first_chunks = repository.replace_chunks(project.id, first.id, ["이서하는 강도윤과 동행했다."])
    second_chunks = repository.replace_chunks(project.id, second.id, ["이서하는 강도윤을 의심했다."])

    seoha = repository.upsert_entity(project.id, "character", "이서하", [], "기록관", first.id)
    doyun = repository.upsert_entity(project.id, "character", "강도윤", [], "호위", first.id)
    repository.add_relation(project.id, seoha.id, doyun.id, "동행/협력", 0.8, first_chunks)
    repository.add_relation(project.id, seoha.id, doyun.id, "적대/의심", 0.82, second_chunks)
    repository.replace_episode_analysis(
        project.id,
        first.id,
        first.content_hash,
        {
            "entities": [
                {"type": "character", "name": "이서하", "summary": "기록관", "aliases": []},
                {"type": "character", "name": "강도윤", "summary": "호위", "aliases": []},
            ],
            "relations": [
                {"source": "이서하", "target": "강도윤", "type": "동행/협력", "confidence": 0.8},
            ],
            "issues": [],
        },
        model_name="fake.gguf",
        prompt_version="test-v1",
    )
    repository.replace_episode_analysis(
        project.id,
        second.id,
        second.content_hash,
        {
            "entities": [
                {"type": "character", "name": "이서하", "summary": "기록관", "aliases": []},
                {"type": "character", "name": "강도윤", "summary": "호위", "aliases": []},
            ],
            "relations": [
                {"source": "이서하", "target": "강도윤", "type": "적대/의심", "confidence": 0.82},
            ],
            "issues": [],
        },
        model_name="fake.gguf",
        prompt_version="test-v1",
    )

    documents = repository.list_documents(project.id)
    first_range = repository.graph(project.id, start_chapter=0, end_chapter=0)
    full_graph = repository.graph(project.id)

    assert [document.analysis_status for document in documents] == ["analyzed", "analyzed"]
    assert {relation.type for relation in first_range.relations} == {"동행/협력"}
    assert first_range.range.continuity_ready is False
    assert len(full_graph.changes) == 1
    assert full_graph.changes[0].previous_type == "동행/협력"
    assert full_graph.changes[0].current_type == "적대/의심"
