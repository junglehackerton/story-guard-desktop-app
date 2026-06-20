from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app


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
    assert client.get("/projects").status_code == 401
    assert client.get("/projects", headers={"X-Story-Guard-Token": "wrong"}).status_code == 401

    response = client.get("/projects", headers={"X-Story-Guard-Token": "test-token"})

    assert response.status_code == 200


def test_settings_round_trip() -> None:
    client = TestClient(app)

    response = client.put(
        "/settings",
        json={"generation_model": "qwen2.5:7b", "embedding_model": "embeddinggemma"},
    )

    assert response.status_code == 200
    assert response.json()["generation_model"] == "qwen2.5:7b"
    assert client.get("/settings").json()["generation_model"] == "qwen2.5:7b"

    client.put("/settings", json={"generation_model": "", "embedding_model": "embeddinggemma"})


def test_project_title_can_be_updated() -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "초안 제목"}).json()

    response = client.patch(f"/projects/{project['id']}", json={"title": "유리 종루의 밤"})

    assert response.status_code == 200
    assert response.json()["title"] == "유리 종루의 밤"
    projects = client.get("/projects").json()
    assert any(item["id"] == project["id"] and item["title"] == "유리 종루의 밤" for item in projects)


def test_document_can_be_deleted_and_analysis_is_cleared(tmp_path: Path) -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "삭제 테스트"}).json()
    story = tmp_path / "delete-me.md"
    story.write_text("인물: 아린, 도윤\n아린과 도윤은 함께 검은 종루에 갔다.", encoding="utf-8")
    document = client.post("/documents/import", json={"project_id": project["id"], "path": str(story)}).json()
    client.post(f"/projects/{project['id']}/analyze")
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
    assert body["embedding_model"] == "embeddinggemma"
    assert body["generation_model"] == "qwen2.5:3b"
    assert isinstance(body["models"], list)


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
    client.post("/documents/import", json={"project_id": project["id"], "path": str(story)})
    client.post(f"/projects/{project['id']}/analyze")
    graph = client.get(f"/projects/{project['id']}/graph").json()

    response = client.get(f"/issues/{graph['issues'][0]['id']}/evidence")

    assert response.status_code == 200
    assert "충돌" in response.json()[0]["text"]
