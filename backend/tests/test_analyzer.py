from pathlib import Path

from backend.app.database import Database
from backend.app.pipeline.analyzer import StoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.parser import read_document, split_chunks


def test_analyzer_extracts_entities_and_continuity_issue(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("한국어 샘플")
    story_path = tmp_path / "story.txt"
    story_path.write_text(
        "\n".join(
            [
                "인물: 한서윤, 강도하",
                "장소: 흑월성",
                "아이템: 검은 열쇠",
                "떡밥: 검은 열쇠는 봉인된 문을 연다",
                "강도하는 한서윤을 모른다.",
                "후반에 강도하는 한서윤을 이미 알고 있었다. 앞에서는 모른다 했지만 충돌한다.",
            ]
        ),
        encoding="utf-8",
    )
    content, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project.id,
        path=story_path,
        title="story",
        file_format=file_format,
        content_hash=digest,
        content=content,
    )
    repository.replace_chunks(project.id, document.id, split_chunks(content))

    result = StoryAnalyzer(repository).analyze_project(project.id)
    graph = repository.graph(project.id)

    assert result.entity_count >= 4
    assert any(entity.name == "한서윤" for entity in graph.entities)
    issue = next(issue for issue in graph.issues if issue.category == "contradiction")
    assert issue.evidence_chunk_ids


class FakeLlmExtractor:
    def enabled(self) -> bool:
        return True

    def extract_story_facts(self, text: str) -> dict:
        return {
            "entities": [
                {"type": "character", "name": "한서윤", "summary": "주인공", "aliases": ["서윤"]},
                {"type": "item", "name": "검은 열쇠", "summary": "봉인을 여는 물건", "aliases": []},
            ],
            "relations": [
                {"source": "한서윤", "target": "검은 열쇠", "type": "owns", "confidence": 0.8}
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


def test_analyzer_uses_local_llm_when_configured(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("LLM 작품")
    story_path = tmp_path / "story.txt"
    story_path.write_text("한서윤은 검은 열쇠를 들고 흑월성에 갔다.", encoding="utf-8")
    content, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project.id,
        path=story_path,
        title="story",
        file_format=file_format,
        content_hash=digest,
        content=content,
    )
    repository.replace_chunks(project.id, document.id, split_chunks(content))

    result = StoryAnalyzer(repository, llm=FakeLlmExtractor()).analyze_project(project.id)
    graph = repository.graph(project.id)

    assert result.entity_count == 2
    assert graph.relations[0].type == "소유/사용"
    assert graph.issues[0].title == "LLM 설정 충돌"


class SparseLlmExtractor:
    def enabled(self) -> bool:
        return True

    def extract_story_facts(self, text: str) -> dict:
        return {
            "entities": [
                {"type": "character", "name": "한서윤", "summary": "기록관", "aliases": []},
                {"type": "item", "name": "검은 열쇠", "summary": "결계 열쇠", "aliases": []},
            ],
            "relations": [],
            "issues": [],
        }


def test_analyzer_supplements_sparse_llm_with_explicit_graph_and_conflicts(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("관계 보강 작품")
    story_path = tmp_path / "story.txt"
    story_path.write_text(
        "\n".join(
            [
                "인물: 한서윤, 강도하",
                "장소: 흑월성",
                "조직: 은월회",
                "아이템: 검은 열쇠",
                "설정: 흑월성 결계는 검은 열쇠로만 열린다",
                "떡밥: 검은 열쇠 표면의 세 별 문양은 사라진 왕가의 표식이다",
                "한서윤은 은월회 기록관이며 검은 열쇠를 들고 흑월성으로 간다.",
                "강도하는 한서윤을 모른다.",
                "하지만 후반에 강도하는 한서윤을 이미 알고 있었다. 앞에서는 모른다 했지만 충돌한다.",
            ]
        ),
        encoding="utf-8",
    )
    content, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project.id,
        path=story_path,
        title="story",
        file_format=file_format,
        content_hash=digest,
        content=content,
    )
    repository.replace_chunks(project.id, document.id, split_chunks(content))

    result = StoryAnalyzer(repository, llm=SparseLlmExtractor()).analyze_project(project.id)
    graph = repository.graph(project.id)
    names = {entity.name for entity in graph.entities}
    types = {entity.type for entity in graph.entities}

    assert result.entity_count >= 6
    assert {"한서윤", "강도하", "흑월성", "은월회", "검은 열쇠"}.issubset(names)
    assert {"character", "place", "organization", "item", "rule", "foreshadowing"}.issubset(types)
    assert result.relation_count >= 4
    assert any(issue.category == "contradiction" for issue in graph.issues)


def test_analyzer_classifies_relationship_context_for_graph_styling(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("관계 색상 작품")
    story_path = tmp_path / "story.txt"
    story_path.write_text(
        "\n".join(
            [
                "인물: 아린, 도윤",
                "장소: 검은 종루",
                "조직: 청백회",
                "아이템: 은색 회중시계",
                "아린과 도윤은 어린 시절부터 친구였고 도윤은 아린을 보호했다.",
                "아린은 은색 회중시계를 들고 검은 종루에 갔다.",
                "아린은 청백회를 대화재의 원인이라고 의심했고 청백회는 아린과 적대했다.",
            ]
        ),
        encoding="utf-8",
    )
    content, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project.id,
        path=story_path,
        title="story",
        file_format=file_format,
        content_hash=digest,
        content=content,
    )
    repository.replace_chunks(
        project.id,
        document.id,
        [
            "아린과 도윤은 어린 시절부터 친구였고 도윤은 아린을 보호했다.",
            "아린은 은색 회중시계를 들고 검은 종루에 갔다.",
            "아린은 청백회를 대화재의 원인이라고 의심했고 청백회는 아린과 적대했다.",
        ],
    )

    StoryAnalyzer(repository).analyze_project(project.id)
    graph = repository.graph(project.id)
    relation_types = {relation.type for relation in graph.relations}

    assert "동행/협력" in relation_types
    assert "소유/사용" in relation_types
    assert "등장 장소" in relation_types
    assert "적대/의심" in relation_types
    assert max(relation.confidence for relation in graph.relations) > 0.8


class HanjaRelationLlmExtractor:
    def enabled(self) -> bool:
        return True

    def extract_story_facts(self, text: str) -> dict:
        return {
            "entities": [
                {"type": "character", "name": "서지안", "summary": "기록관", "aliases": []},
                {"type": "character", "name": "류하겸", "summary": "감찰관", "aliases": []},
                {"type": "item", "name": "청동 나침반", "summary": "항해 도구", "aliases": []},
            ],
            "relations": [
                {"source": "서지안", "target": "류하겸", "type": "同行", "confidence": 0.82},
                {"source": "서지안", "target": "청동 나침반", "type": "關係情報-複雜候有", "confidence": 0.71},
            ],
            "issues": [],
        }


def test_analyzer_normalizes_non_korean_relation_labels(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("한자 라벨 작품")
    story_path = tmp_path / "story.txt"
    story_path.write_text("서지안은 류하겸과 청동 나침반을 조사했다.", encoding="utf-8")
    content, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project.id,
        path=story_path,
        title="story",
        file_format=file_format,
        content_hash=digest,
        content=content,
    )
    repository.replace_chunks(project.id, document.id, split_chunks(content))

    StoryAnalyzer(repository, llm=HanjaRelationLlmExtractor()).analyze_project(project.id)
    graph = repository.graph(project.id)
    relation_types = {relation.type for relation in graph.relations}
    display_labels = {relation.display_label for relation in graph.relations}

    assert "同行" not in relation_types
    assert "關係情報-複雜候有" not in display_labels
    assert "동행/협력" in relation_types
    assert "정보/단서" in relation_types


def test_analyzer_does_not_spread_hostility_across_whole_chunk(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("관계 편향 방지 작품")
    story_path = tmp_path / "story.txt"
    story_path.write_text(
        "\n".join(
            [
                "인물: 서지안, 류하겸, 오윤서",
                "조직: 청묵회",
                "서지안은 류하겸과 함께 회색도서관을 조사했다.",
                "오윤서는 청묵회와 몰래 거래했다.",
            ]
        ),
        encoding="utf-8",
    )
    content, file_format, digest = read_document(story_path)
    document = repository.add_document(
        project_id=project.id,
        path=story_path,
        title="story",
        file_format=file_format,
        content_hash=digest,
        content=content,
    )
    repository.replace_chunks(project.id, document.id, [content])

    StoryAnalyzer(repository).analyze_project(project.id)
    graph = repository.graph(project.id)
    relation_types = [relation.type for relation in graph.relations]

    assert "동행/협력" in relation_types
    assert "비밀/거래" in relation_types
    assert relation_types.count("적대/의심") < len(relation_types)


def test_analyzer_flags_late_arrivals_and_disappearing_entities(tmp_path: Path) -> None:
    repository = StoryRepository(Database(tmp_path / "test.sqlite"))
    project = repository.create_project("편별 변화 작품")
    episodes = [
        (
            "1화",
            "\n".join(
                [
                    "인물: 아린, 도윤",
                    "아이템: 은색 회중시계",
                    "떡밥: 은색 회중시계는 아린의 거짓말에 반응한다",
                    "아린은 도윤과 함께 은색 회중시계를 들고 검은 종루로 갔다. 도윤은 아린을 보호했다.",
                ]
            ),
        ),
        (
            "2화",
            "\n".join(
                [
                    "인물: 아린, 도윤",
                    "아이템: 은색 회중시계",
                    "아린과 도윤은 은색 회중시계를 조사했다. 도윤은 다시 아린을 보호했다.",
                ]
            ),
        ),
        (
            "3화",
            "\n".join(
                [
                    "인물: 아린, 마리아",
                    "아이템: 검은 실의 나침반",
                    "규칙: 유리문은 피를 떨어뜨리면 낮에도 열린다",
                    "마리아는 검은 실의 나침반을 아린에게 주었다. 앞서 다친 동료의 행방은 설명되지 않는다.",
                ]
            ),
        ),
    ]
    for index, (title, content) in enumerate(episodes, start=1):
        path = tmp_path / f"episode-{index}.md"
        path.write_text(content, encoding="utf-8")
        _, file_format, digest = read_document(path)
        document = repository.add_document(
            project_id=project.id,
            path=path,
            title=title,
            file_format=file_format,
            content_hash=digest,
            content=content,
            chapter_index=index,
        )
        repository.replace_chunks(project.id, document.id, split_chunks(content))

    StoryAnalyzer(repository).analyze_project(project.id)
    graph = repository.graph(project.id)
    entities = {entity.name: entity for entity in graph.entities}
    issue_titles = {issue.title for issue in graph.issues}

    assert entities["검은 실의 나침반"].appearance_state == "new"
    assert entities["도윤"].appearance_state in {"fading", "dormant"}
    assert entities["도윤"].mention_count > entities["마리아"].mention_count
    assert "후반부 갑작스런 설정 등장" in issue_titles
    assert "언급이 끊긴 설정 후보" in issue_titles
