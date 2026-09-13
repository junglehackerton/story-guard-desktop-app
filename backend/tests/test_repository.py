from pathlib import Path
import json

from backend.app.database import Database
from backend.app.models import AnalysisStatus
from backend.app.repository import StoryRepository, normalize_relation_type, relation_types_conflict


def test_relation_types_conflict_supports_specific_predicates() -> None:
    assert relation_types_conflict({"계약 체결", "계약 거절"})
    assert relation_types_conflict({"보호함", "적대"})
    assert not relation_types_conflict({"등장", "이동"})


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


def test_graph_health_separates_isolated_and_generic_relationships(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "health.sqlite"))
    project = repository.create_project("관계 건강도 테스트")
    first = repository.upsert_entity(project.id, "character", "도윤", [], "", None)
    second = repository.upsert_entity(project.id, "character", "아린", [], "", None)
    repository.upsert_entity(project.id, "item", "봉인검", [], "", None)
    repository.add_relation(project.id, first.id, second.id, "관계", 0.6, [])

    graph = repository.graph(project.id)

    assert graph.health.connected_entity_count == 2
    assert graph.health.component_count == 1
    assert graph.health.isolated_entity_count == 1
    assert graph.health.generic_relation_count == 1
    assert graph.health.unsupported_relation_count == 1


def test_relation_timeline_marks_changed_and_explicit_break(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "timeline.sqlite"))
    project = repository.create_project("회차 관계 흐름 테스트")
    first_doc = repository.add_document(project.id, Path("1.txt"), "1화", "txt", "h1", "도윤은 아린을 지켰다.", 0)
    second_doc = repository.add_document(project.id, Path("2.txt"), "2화", "txt", "h2", "도윤과 아린의 동맹은 해제됐다.", 1)
    repository.replace_chunks(project.id, first_doc.id, [first_doc.content])
    repository.replace_chunks(project.id, second_doc.id, [second_doc.content])
    first = repository.upsert_entity(project.id, "character", "도윤", [], "", first_doc.id)
    second = repository.upsert_entity(project.id, "character", "아린", [], "", first_doc.id)
    with repository.database.connect() as connection:
        connection.execute("INSERT INTO episode_relations(project_id,document_id,source_name,target_name,type,evidence_chunk_ids) VALUES(?,?,?,?,?,?)", (project.id, first_doc.id, "도윤", "아린", "동행/협력", "[]"))
        connection.execute("INSERT INTO episode_relations(project_id,document_id,source_name,target_name,type,evidence_chunk_ids) VALUES(?,?,?,?,?,?)", (project.id, second_doc.id, "도윤", "아린", "관계 해제", "[]"))
    graph = repository.graph(project.id)
    assert [event.status for event in graph.timeline] == ["observed", "explicit_break"]
    assert graph.timeline[1].chapter_index == 1
    assert graph.health.explicit_break_count == 1


def test_relation_timeline_marks_middle_chapter_gap_without_calling_it_break(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "timeline-gap.sqlite"))
    project = repository.create_project("중간 공백 관계 흐름 테스트")
    docs = [
        repository.add_document(project.id, Path("1.txt"), "1화", "txt", "g1", "도윤은 아린을 지켰다.", 0),
        repository.add_document(project.id, Path("2.txt"), "2화", "txt", "g2", "성문이 무너졌다.", 1),
        repository.add_document(project.id, Path("3.txt"), "3화", "txt", "g3", "도윤은 다시 아린을 지켰다.", 2),
    ]
    for doc in docs:
        repository.replace_chunks(project.id, doc.id, [doc.content])
    repository.upsert_entity(project.id, "character", "도윤", [], "", docs[0].id)
    repository.upsert_entity(project.id, "character", "아린", [], "", docs[0].id)
    with repository.database.connect() as connection:
        connection.executemany(
            "INSERT INTO episode_relations(project_id,document_id,source_name,target_name,type,evidence_chunk_ids) VALUES(?,?,?,?,?,?)",
            [(project.id, docs[0].id, "도윤", "아린", "동행/협력", "[]"),
             (project.id, docs[2].id, "도윤", "아린", "동행/협력", "[]")],
        )
    graph = repository.graph(project.id)
    assert [event.status for event in graph.timeline] == ["observed", "gap"]
    assert graph.health.gap_relation_count == 1
    assert graph.health.explicit_break_count == 0


def test_relation_timeline_skips_ambiguous_alias_instead_of_attributing_event(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "timeline-ambiguous.sqlite"))
    project = repository.create_project("모호한 별칭 회차 흐름 테스트")
    document = repository.add_document(project.id, Path("1.txt"), "1화", "txt", "a1", "대장이 봉인검을 들었다.", 0)
    repository.replace_chunks(project.id, document.id, [document.content])
    repository.upsert_entity(project.id, "character", "서윤", ["대장"], "북부 대장", document.id)
    repository.upsert_entity(project.id, "character", "도윤", ["대장"], "남부 대장", document.id)
    repository.upsert_entity(project.id, "item", "봉인검", [], "계약 검", document.id)
    with repository.database.connect() as connection:
        connection.execute(
            "INSERT INTO episode_relations(project_id,document_id,source_name,target_name,type,evidence_chunk_ids) VALUES(?,?,?,?,?,?)",
            (project.id, document.id, "대장", "봉인검", "사용", "[]"),
        )

    graph = repository.graph(project.id)

    assert graph.timeline == []
    assert graph.changes == []


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
    assert cancelled.progress == 42
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
    assert first_range.range.continuity_ready is True
    assert first_range.range.message == "선택 범위의 설정 붕괴 후보를 판단합니다."
    assert len(full_graph.changes) == 1
    assert full_graph.changes[0].previous_type == "동행/협력"
    assert full_graph.changes[0].current_type == "적대/의심"


def test_story_settings_keep_confirmed_and_draft_separate(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "settings.sqlite"))
    project = repository.create_project("설정 메모 테스트")
    confirmed = repository.add_story_setting(project.id, "봉인검 조건", "계약자만 사용할 수 있다.", "confirmed")
    draft = repository.add_story_setting(project.id, "후속 아이디어", "예외 계약을 추가할 수도 있다.", "draft")
    assert [(item.title, item.certainty) for item in repository.list_story_settings(project.id)] == [
        ("봉인검 조건", "confirmed"), ("후속 아이디어", "draft")
    ]
    updated = repository.update_story_setting(draft.id, draft.title, draft.content, "confirmed")
    assert updated.certainty == "confirmed"
    assert repository.delete_story_setting(confirmed.id) == project.id


def test_graph_health_infers_middle_gap_from_non_adjacent_observations(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "gap.sqlite"))
    project = repository.create_project("공백 추론")
    docs = []
    for index in (0, 3):
        document = repository.add_document(
            project.id, tmp_path / f"episode-{index}.txt", f"{index + 1}화", "txt",
            f"hash-{index}", "유나가 봉인검을 들었다.", chapter_index=index,
        )
        repository.replace_chunks(project.id, document.id, ["유나가 봉인검을 들었다."])
        docs.append(document)
    yuna = repository.upsert_entity(project.id, "character", "유나", [], "인물", docs[0].id)
    sword = repository.upsert_entity(project.id, "item", "봉인검", [], "검", docs[0].id)
    for document in docs:
        chunk_id = repository.list_chunks(project.id)[-1 if document.chapter_index == 3 else 0]["id"]
        repository.add_relation(project.id, yuna.id, sword.id, "사용함", 0.8, [chunk_id])
    for document in docs:
        repository.replace_episode_analysis(
            project.id, document.id, document.content_hash,
            {"entities": [{"type": "character", "name": "유나", "summary": "인물", "aliases": []},
                           {"type": "item", "name": "봉인검", "summary": "검", "aliases": []}],
             "relations": [{"source": "유나", "target": "봉인검", "type": "사용함", "confidence": 0.8}], "issues": []},
            model_name="fake.gguf", prompt_version="test-v1",
        )
    graph = repository.graph(project.id)
    assert graph.health.gap_relation_count == 1


def test_foreshadowing_status_is_persisted_per_entity(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "foreshadowing.sqlite"))
    project = repository.create_project("떡밥 상태 테스트")
    entity = repository.upsert_entity(project.id, "foreshadowing", "사라진 편지", [], "후속 단서", None)
    assert repository.list_foreshadowing_statuses(project.id) == []
    saved = repository.set_foreshadowing_status(project.id, entity.id, "in_progress")
    assert saved.status == "in_progress"
    assert repository.list_foreshadowing_statuses(project.id)[0].entity_id == entity.id
