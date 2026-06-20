from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.database import Database
from backend.app.main import app, repository
from backend.app.repository import StoryRepository


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_local_dev_origin_cors_preflight() -> None:
    client = TestClient(app)

    response = client.options(
        "/projects",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_api_token_is_required_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("STORY_GUARD_API_TOKEN", "test-token")
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 401
    assert client.get("/health/ready", headers={"X-Story-Guard-Token": "test-token"}).status_code == 200
    assert client.get("/projects").status_code == 401
    assert client.get("/projects", headers={"X-Story-Guard-Token": "wrong"}).status_code == 401

    response = client.get("/projects", headers={"X-Story-Guard-Token": "test-token"})

    assert response.status_code == 200


def test_settings_round_trip() -> None:
    client = TestClient(app)

    response = client.put(
        "/settings",
        json={
            "generation_model": "local-story-model.gguf",
            "embedding_model": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        },
    )

    assert response.status_code == 200
    assert response.json()["generation_model"] == "local-story-model.gguf"
    assert client.get("/settings").json()["generation_model"] == "local-story-model.gguf"

    client.put(
        "/settings",
        json={
            "generation_model": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "embedding_model": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        },
    )


def test_project_title_can_be_updated() -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "초안 제목"}).json()

    response = client.patch(f"/projects/{project['id']}", json={"title": "유리 종루의 밤"})

    assert response.status_code == 200
    assert response.json()["title"] == "유리 종루의 밤"
    projects = client.get("/projects").json()
    assert any(item["id"] == project["id"] and item["title"] == "유리 종루의 밤" for item in projects)


def test_empty_project_list_does_not_create_default_project(monkeypatch, tmp_path: Path) -> None:
    isolated_repository = StoryRepository(Database(tmp_path / "empty-projects.sqlite"))
    monkeypatch.setattr(main_module, "repository", isolated_repository)
    client = TestClient(app)

    response = client.get("/projects")

    assert response.status_code == 200
    assert response.json() == []
    assert isolated_repository.list_projects() == []


def test_project_can_be_deleted_with_owned_data(tmp_path: Path) -> None:
    client = TestClient(app)
    survivor = client.post("/projects", json={"title": "남길 작품"}).json()
    project = client.post("/projects", json={"title": "삭제할 작품"}).json()
    story = tmp_path / "delete-project.md"
    story.write_text("인물: 아린, 도윤\n아린은 도윤과 백야단에 들어갔다.", encoding="utf-8")
    document = client.post("/documents/import", json={"project_id": project["id"], "path": str(story)}).json()
    arin = repository.upsert_entity(
        project_id=project["id"],
        entity_type="character",
        name="아린",
        aliases=[],
        summary="삭제 테스트용 인물",
        first_seen_document_id=document["id"],
    )
    doyun = repository.upsert_entity(
        project_id=project["id"],
        entity_type="character",
        name="도윤",
        aliases=[],
        summary="삭제 테스트용 인물",
        first_seen_document_id=document["id"],
    )
    repository.add_relation(project["id"], arin.id, doyun.id, "동행/협력", 0.8, [1])
    repository.add_issue(project["id"], "medium", "relationship", "삭제 테스트 이슈", "삭제되어야 한다.", [1])

    response = client.delete(f"/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json()["project_id"] == project["id"]
    projects = client.get("/projects").json()
    assert any(item["id"] == survivor["id"] for item in projects)
    assert all(item["id"] != project["id"] for item in projects)
    assert client.get(f"/projects/{project['id']}/documents").json() == []
    assert repository.list_chunks(project["id"]) == []
    graph = client.get(f"/projects/{project['id']}/graph").json()
    assert graph["entities"] == []
    assert graph["relations"] == []
    assert graph["issues"] == []


def test_project_delete_succeeds_when_vector_index_cleanup_fails(monkeypatch) -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "인덱스 정리 실패 테스트"}).json()

    def fail_delete_index(self, project_id: int) -> None:
        raise RuntimeError("chroma cleanup failed")

    monkeypatch.setattr(main_module.RagService, "delete_project_index", fail_delete_index)

    response = client.delete(f"/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json()["project_id"] == project["id"]
    assert all(item["id"] != project["id"] for item in client.get("/projects").json())


def test_document_can_be_deleted_and_analysis_is_cleared(tmp_path: Path) -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "삭제 테스트"}).json()
    story = tmp_path / "delete-me.md"
    story.write_text("인물: 아린, 도윤\n아린과 도윤은 함께 검은 종루에 갔다.", encoding="utf-8")
    document = client.post("/documents/import", json={"project_id": project["id"], "path": str(story)}).json()
    repository.upsert_entity(
        project_id=project["id"],
        entity_type="character",
        name="아린",
        aliases=[],
        summary="삭제 테스트용 엔티티",
        first_seen_document_id=document["id"],
    )
    assert client.get(f"/projects/{project['id']}/graph").json()["entities"]

    response = client.delete(f"/documents/{document['id']}")

    assert response.status_code == 200
    assert response.json()["project_id"] == project["id"]
    assert client.get(f"/projects/{project['id']}/documents").json() == []
    graph = client.get(f"/projects/{project['id']}/graph").json()
    assert graph["entities"] == []
    assert graph["relations"] == []
    assert graph["issues"] == []


def test_setup_status_endpoint_reports_environment_shape() -> None:
    client = TestClient(app)

    response = client.get("/setup/status")

    assert response.status_code == 200
    body = response.json()
    assert "ready" in body
    assert body["embedding_model"] == "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    assert isinstance(body["generation_model"], str)
    assert isinstance(body["models"], list)
    assert body["runtime_installed"] is True


def test_setup_progress_endpoint_reports_idle_state() -> None:
    client = TestClient(app)

    response = client.get("/setup/progress")

    assert response.status_code == 200
    body = response.json()
    assert body["running"] is False
    assert "stage" in body


def test_issue_evidence_endpoint_returns_chunks(tmp_path: Path) -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "근거 테스트"}).json()
    story = tmp_path / "story.txt"
    story.write_text(
        "인물: 한서윤\n강도하는 한서윤을 모른다.\n후반에 이미 알고 있었다. 앞에서는 모른다 했지만 충돌한다.",
        encoding="utf-8",
    )
    document = client.post("/documents/import", json={"project_id": project["id"], "path": str(story)}).json()
    chunk = repository.list_chunks(project["id"])[0]
    issue = repository.add_issue(
        project_id=project["id"],
        severity="high",
        category="contradiction",
        title="설정 충돌",
        description="앞에서는 모른다고 했지만 후반에 이미 알고 있었다.",
        evidence_chunk_ids=[chunk["id"]],
    )

    response = client.get(f"/issues/{issue.id}/evidence")

    assert response.status_code == 200
    assert "충돌" in response.json()[0]["text"]


def test_graph_endpoint_accepts_chapter_range(tmp_path: Path) -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "범위 그래프 API 테스트"}).json()
    first_story = tmp_path / "range-01.md"
    second_story = tmp_path / "range-02.md"
    first_story.write_text("이서하는 강도윤과 동행했다.", encoding="utf-8")
    second_story.write_text("이서하는 강도윤을 의심했다.", encoding="utf-8")
    first = client.post("/documents/import", json={"project_id": project["id"], "path": str(first_story)}).json()
    second = client.post("/documents/import", json={"project_id": project["id"], "path": str(second_story)}).json()
    first_chunks = [chunk["id"] for chunk in repository.list_chunks(project["id"]) if chunk["document_id"] == first["id"]]
    second_chunks = [chunk["id"] for chunk in repository.list_chunks(project["id"]) if chunk["document_id"] == second["id"]]
    seoha = repository.upsert_entity(project["id"], "character", "이서하", [], "기록관", first["id"])
    doyun = repository.upsert_entity(project["id"], "character", "강도윤", [], "호위", first["id"])
    repository.add_relation(project["id"], seoha.id, doyun.id, "동행/협력", 0.8, first_chunks)
    repository.add_relation(project["id"], seoha.id, doyun.id, "적대/의심", 0.8, second_chunks)
    repository.replace_episode_analysis(
        project["id"],
        first["id"],
        first["content_hash"],
        {
            "entities": [
                {"type": "character", "name": "이서하", "summary": "기록관", "aliases": []},
                {"type": "character", "name": "강도윤", "summary": "호위", "aliases": []},
            ],
            "relations": [{"source": "이서하", "target": "강도윤", "type": "동행/협력", "confidence": 0.8}],
            "issues": [],
        },
    )
    repository.replace_episode_analysis(
        project["id"],
        second["id"],
        second["content_hash"],
        {
            "entities": [
                {"type": "character", "name": "이서하", "summary": "기록관", "aliases": []},
                {"type": "character", "name": "강도윤", "summary": "호위", "aliases": []},
            ],
            "relations": [{"source": "이서하", "target": "강도윤", "type": "적대/의심", "confidence": 0.8}],
            "issues": [],
        },
    )

    response = client.get(f"/projects/{project['id']}/graph?start_chapter=0&end_chapter=0")

    assert response.status_code == 200
    body = response.json()
    assert body["range"]["document_count"] == 1
    assert {relation["type"] for relation in body["relations"]} == {"동행/협력"}


def test_analyze_requires_installed_local_llm(tmp_path: Path) -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "LLM 필요 테스트"}).json()
    story = tmp_path / "story.txt"
    story.write_text("인물: 한서윤\n한서윤은 검은 열쇠를 들었다.", encoding="utf-8")
    client.post("/documents/import", json={"project_id": project["id"], "path": str(story)})

    response = client.post(f"/projects/{project['id']}/analyze")

    assert response.status_code == 409
    assert "로컬 LLM 모델" in response.json()["detail"]

    status_response = client.get(f"/projects/{project['id']}/analysis/status")

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "failed"
    assert status_response.json()["current_step"] == "failed"
    assert status_response.json()["progress"] == 100


def test_analyze_rejects_project_that_is_already_running() -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "중복 분석 API 테스트"}).json()
    existing = repository.create_job(
        project["id"],
        main_module.AnalysisStatus.running,
        "이미 분석 중",
        current_step="extract",
        progress=42,
    )

    try:
        response = client.post(f"/projects/{project['id']}/analyze")

        assert response.status_code == 409
        assert "이미 분석" in response.json()["detail"]
        assert repository.running_analysis_job(project["id"]).id == existing.id
    finally:
        repository.cancel_analysis(project["id"])


def test_cancel_analysis_endpoint_stops_running_job_and_clears_graph() -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "취소 API 테스트"}).json()
    job = repository.create_job(
        project["id"],
        main_module.AnalysisStatus.running,
        "분석 중",
        current_step="extract",
        progress=42,
    )
    repository.upsert_entity(
        project_id=project["id"],
        entity_type="character",
        name="한서윤",
        aliases=[],
        summary="삭제되어야 한다.",
        first_seen_document_id=None,
    )

    response = client.post(f"/projects/{project['id']}/analysis/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job.id
    assert body["status"] == "cancelled"
    assert body["current_step"] == "cancelled"
    assert body["progress"] == 100
    assert client.get(f"/projects/{project['id']}/graph").json()["entities"] == []
