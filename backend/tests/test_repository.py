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
