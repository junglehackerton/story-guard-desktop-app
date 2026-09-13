from pathlib import Path
import hashlib

from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.database import Database
from backend.app.main import app, repository
from backend.app.main import analysis_batch_count, recommend_analysis_plan
from backend.app.repository import StoryRepository


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analysis_plan_boundaries() -> None:
    assert recommend_analysis_plan(0)[0:2] == ("full", 1)
    assert recommend_analysis_plan(20)[0:2] == ("full", 20)
    assert recommend_analysis_plan(21)[0:2] == ("segmented", 20)
    assert recommend_analysis_plan(100)[0:2] == ("segmented", 20)
    assert recommend_analysis_plan(101)[0:2] == ("staged", 20)
    assert analysis_batch_count(0, 20) == 0
    assert analysis_batch_count(21, 20) == 2
    assert analysis_batch_count(101, 20) == 6


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


def test_loopback_smoke_ports_are_allowed_by_cors() -> None:
    client = TestClient(app)

    response = client.options(
        "/projects",
        headers={
            "Origin": "http://127.0.0.1:5181",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-story-guard-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5181"


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


def test_story_setting_api_round_trip() -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "설정 API"}).json()
    created = client.post(f"/projects/{project['id']}/settings", json={
        "title": "사용 조건", "content": "계약자만 사용할 수 있다.", "certainty": "confirmed"
    })
    assert created.status_code == 200
    setting = created.json()
    assert client.get(f"/projects/{project['id']}/settings").json()[0]["certainty"] == "confirmed"
    updated = client.patch(f"/settings/{setting['id']}", json={
        "title": "사용 조건", "content": "계약자 또는 예외 계약자만 사용할 수 있다.", "certainty": "draft"
    })
    assert updated.status_code == 200
    assert updated.json()["certainty"] == "draft"
    assert client.delete(f"/settings/{setting['id']}").json() == {"project_id": project["id"]}


def test_empty_project_list_does_not_create_default_project(monkeypatch, tmp_path: Path) -> None:
    isolated_repository = StoryRepository(Database(tmp_path / "empty-projects.sqlite"))
    monkeypatch.setattr(main_module, "repository", isolated_repository)
    client = TestClient(app)

    response = client.get("/projects")

    assert response.status_code == 200
    assert response.json() == []
    assert isolated_repository.list_projects() == []


def test_project_list_includes_analysis_and_review_summary(tmp_path: Path) -> None:
    isolated_repository = StoryRepository(Database(tmp_path / "project-summary.sqlite"))
    project = isolated_repository.create_project("작품 요약")
    story = tmp_path / "chapter-1.md"
    content = "유나는 봉인검을 들었다."
    story.write_text(content, encoding="utf-8")
    document = isolated_repository.add_document(
        project_id=project.id,
        path=story,
        title="1화",
        file_format="md",
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content=content,
        chapter_index=0,
    )
    isolated_repository.add_issue(
        project.id,
        "medium",
        "contradiction",
        "확인할 관계",
        "근거를 확인해 주세요.",
        [],
    )

    pending = isolated_repository.list_projects()[0]
    assert pending.document_count == 1
    assert pending.pending_document_count == 1
    assert pending.open_issue_count == 1
    assert pending.last_analyzed_at is None

    isolated_repository.upsert_document_analysis_cache(
        document_id=document.id,
        project_id=project.id,
        content_hash=document.content_hash,
        payload={"entities": [], "relations": [], "claims": [], "issues": []},
        model_name="test-model",
        prompt_version="test-v1",
    )

    analyzed = isolated_repository.list_projects()[0]
    assert analyzed.document_count == 1
    assert analyzed.pending_document_count == 0
    assert analyzed.open_issue_count == 1
    assert analyzed.last_analyzed_at


def test_importing_new_chapter_keeps_published_graph_visible(tmp_path: Path) -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "증분 보존 API"}).json()
    first_path = tmp_path / "first.txt"
    first_path.write_text("유나는 봉인검을 지켰다.", encoding="utf-8")
    first = client.post("/documents/import", json={"project_id": project["id"], "path": str(first_path)}).json()
    source = repository.upsert_entity(project["id"], "character", "유나", [], "주인공", first["id"])
    target = repository.upsert_entity(project["id"], "item", "봉인검", [], "검", first["id"])
    repository.add_relation(project["id"], source.id, target.id, "지킴", 0.9, [])

    second_path = tmp_path / "second.txt"
    second_path.write_text("새로운 사건이 시작된다.", encoding="utf-8")
    response = client.post("/documents/import", json={"project_id": project["id"], "path": str(second_path)})

    assert response.status_code == 200
    graph = client.get(f"/projects/{project['id']}/graph").json()
    assert {entity["name"] for entity in graph["entities"]} >= {"유나", "봉인검"}
    assert any(relation["type"] == "지킴" for relation in graph["relations"])


def test_replacing_document_keeps_chunks_in_owning_project(tmp_path: Path, monkeypatch) -> None:
    isolated_repository = StoryRepository(Database(tmp_path / "replace.sqlite"))
    monkeypatch.setattr(main_module, "repository", isolated_repository)
    monkeypatch.setattr(main_module, "chroma_path", lambda: tmp_path / "chroma")
    client = TestClient(app)
    project = client.post("/projects", json={"title": "원고 교체 프로젝트"}).json()
    original = tmp_path / "episode-1.txt"
    original.write_text("유나는 항구를 떠났다.", encoding="utf-8")
    document = client.post("/documents/import", json={"project_id": project["id"], "path": str(original)}).json()

    replacement = tmp_path / "episode-1-revised.txt"
    replacement.write_text("유나는 봉인검을 들고 항구를 떠났다. 수정된 장면이다.", encoding="utf-8")
    response = client.put(f"/documents/{document['id']}", json={"path": str(replacement)})

    assert response.status_code == 200
    chunks = isolated_repository.list_chunks(project["id"])
    assert chunks
    assert all(chunk["project_id"] == project["id"] for chunk in chunks)
    assert any("수정된 장면" in chunk["text"] for chunk in chunks)


def test_analysis_estimate_uses_actual_chunk_grouping(tmp_path: Path) -> None:
    client = TestClient(app)
    project = client.post("/projects", json={"title": "분석량 추정"}).json()
    for index in range(21):
        path = tmp_path / f"episode-{index:02d}.txt"
        path.write_text((f"{index + 1}화. 유나는 기록을 확인했다. " * 60), encoding="utf-8")
        response = client.post("/documents/import", json={"project_id": project["id"], "path": str(path)})
        assert response.status_code == 200

    estimate = client.get(f"/projects/{project['id']}/analysis/estimate")

    assert estimate.status_code == 200
    payload = estimate.json()
    assert payload["document_count"] == 21
    assert payload["chunk_count"] > 20
    assert payload["review_window_count"] == 21
    assert payload["manuscript_chars"] == sum(
        len((tmp_path / f"episode-{index:02d}.txt").read_text(encoding="utf-8"))
        for index in range(21)
    )

    ranged = client.get(f"/projects/{project['id']}/analysis/estimate", params={"start_chapter": 5, "end_chapter": 9})
    assert ranged.status_code == 200
    ranged_payload = ranged.json()
    assert ranged_payload["document_count"] == 5
    assert ranged_payload["start_chapter"] == 5
    assert ranged_payload["end_chapter"] == 9

    empty_range = client.get(f"/projects/{project['id']}/analysis/estimate", params={"start_chapter": 99})
    assert empty_range.status_code == 200
    assert empty_range.json()["document_count"] == 0
    assert empty_range.json()["review_window_count"] == 0

    plan = client.get(f"/projects/{project['id']}/analysis/plan")
    assert plan.status_code == 200
    assert plan.json()["mode"] == "segmented"
    assert plan.json()["recommended_batch_size"] == 20
    assert plan.json()["batch_count"] == 2
    assert plan.json()["embedding_estimate_seconds"] == round(plan.json()["chunk_count"] / 1.4)
    assert plan.json()["embedding_memory_estimate_mb"] == 2275
    assert plan.json()["gpt_estimate_seconds"] == plan.json()["review_window_count"] * 30
    assert plan.json()["gpt_estimate_min_seconds"] == plan.json()["review_window_count"] * 15
    assert plan.json()["gpt_estimate_max_seconds"] == plan.json()["review_window_count"] * 60


def test_analysis_estimate_matches_small_project_request_count(tmp_path: Path, monkeypatch) -> None:
    isolated_repository = StoryRepository(Database(tmp_path / "small-estimate.sqlite"))
    project = isolated_repository.create_project("10회 요청 수")
    for index in range(10):
        content = f"{index + 1}화. 유나는 항구의 기록을 확인했다."
        document = isolated_repository.add_document(
            project.id, tmp_path / f"episode-{index}.txt", f"{index + 1}화", "txt",
            hashlib.sha256(content.encode()).hexdigest(), content, index,
        )
        isolated_repository.replace_chunks(project.id, document.id, [content])
    client = TestClient(app)
    # The test repository is installed directly so the endpoint exercises the
    # same estimator used by the desktop UI without constructing a second app.
    monkeypatch.setattr(main_module, "repository", isolated_repository)
    payload = client.get(f"/projects/{project.id}/analysis/estimate").json()
    assert payload["document_count"] == 10
    assert payload["review_window_count"] == 10


def test_gpt_api_resumes_bounded_batches_and_reuses_checkpoints(tmp_path: Path, monkeypatch) -> None:
    """Exercise the public route, rather than only calling the analyzer class."""
    isolated_repository = StoryRepository(Database(tmp_path / "gpt-batch-api.sqlite"))
    project = isolated_repository.create_project("API 배치 재개")
    for index in range(45):
        content = f"{index + 1}화. 유나는 항구의 기록을 확인했다."
        document = isolated_repository.add_document(
            project.id, tmp_path / f"episode-{index}.txt", f"{index + 1}화", "txt",
            hashlib.sha256(content.encode()).hexdigest(), content, index,
        )
        isolated_repository.replace_chunks(project.id, document.id, [content])

    class RagStub:
        def sync_project(self, project_id, progress=None):
            rows = isolated_repository.list_chunks(project_id)
            if progress:
                progress(len(rows), len(rows))
            return len(rows)

        def retrieve(self, project_id, query, limit=4, strategy="hybrid"):
            return []

    class ConnectionStub:
        def __init__(self):
            self.calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            return {"text": '{"entities": [], "relations": [], "issues": []}'}

    connection = ConnectionStub()
    monkeypatch.setattr(main_module, "repository", isolated_repository)
    monkeypatch.setattr(main_module, "RagService", lambda *args, **kwargs: RagStub())
    monkeypatch.setattr(main_module, "chatgpt_connection", connection)
    client = TestClient(app)

    first = client.post(f"/projects/{project.id}/analyze/gpt", json={
        "model": "test-model", "effort": "low", "consent": True, "batch_limit": 20,
    })
    assert first.status_code == 200
    assert first.json()["batch_limited"] is True
    assert first.json()["published"] is False
    assert first.json()["request_count"] == 20

    second = client.post(f"/projects/{project.id}/analyze/gpt", json={
        "model": "test-model", "effort": "low", "consent": True, "batch_limit": 20,
    })
    third = client.post(f"/projects/{project.id}/analyze/gpt", json={
        "model": "test-model", "effort": "low", "consent": True, "batch_limit": 20,
    })
    assert second.json()["batch_limited"] is True
    assert third.json()["published"] is True
    assert third.json()["batch_limited"] is False
    assert connection.calls == 45
    assert isolated_repository.latest_analysis_job(project.id).status.value == "completed"


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
    assert body["embedding_model"] == "Qwen3-Embedding-0.6B-Q8_0.gguf"
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
    assert body["progress"] == 42
    assert client.get(f"/projects/{project['id']}/graph").json()["entities"] == []
