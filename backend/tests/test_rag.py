from pathlib import Path

from backend.app.services.rag import RagService


def test_rag_service_splits_text_with_metadata(tmp_path: Path) -> None:
    rag = RagService(tmp_path / "chroma")

    chunks = rag.split_text(
        "인물: 한서윤\n\n장소: 흑월성\n\n떡밥: 검은 열쇠는 봉인된 문을 연다",
        document_id=7,
        project_id=3,
    )

    assert chunks
    assert chunks[0].metadata["document_id"] == 7
    assert chunks[0].metadata["project_id"] == 3
    assert any("한서윤" in chunk.text for chunk in chunks)


def test_rag_service_builds_chapter_range_filter(tmp_path: Path) -> None:
    rag = RagService(tmp_path / "chroma")

    assert rag._range_filter(1, 5) == {
        "$and": [
            {"chapter_index": {"$gte": 1}},
            {"chapter_index": {"$lte": 5}},
        ]
    }
    assert rag._range_filter(None, None) is None
    assert rag._in_range(3, 1, 5) is True
    assert rag._in_range(0, 1, 5) is False
