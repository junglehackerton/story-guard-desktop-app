from pathlib import Path

from backend.app.services.parser import read_document, split_chunks


def test_read_txt_document(tmp_path: Path) -> None:
    path = tmp_path / "story.txt"
    path.write_text("인물: 한서윤\n장소: 흑월성\n", encoding="utf-8")

    content, file_format, digest = read_document(path)

    assert content.startswith("인물: 한서윤")
    assert file_format == "txt"
    assert len(digest) == 64


def test_split_chunks_preserves_korean_paragraphs() -> None:
    content = "인물: 한서윤\n\n장소: 흑월성\n\n떡밥: 검은 열쇠"

    chunks = split_chunks(content, max_chars=20)

    assert chunks
    assert "한서윤" in chunks[0]
    assert any("검은 열쇠" in chunk for chunk in chunks)
