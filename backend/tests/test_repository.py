from pathlib import Path

from backend.app.database import Database
from backend.app.repository import StoryRepository


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
