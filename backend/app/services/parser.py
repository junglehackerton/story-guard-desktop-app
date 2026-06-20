from __future__ import annotations

import hashlib
from pathlib import Path


SUPPORTED_FORMATS = {".txt", ".md", ".docx"}


class UnsupportedDocumentFormat(ValueError):
    pass


def read_document(path: str | Path) -> tuple[str, str, str]:
    document_path = Path(path).expanduser().resolve()
    suffix = document_path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise UnsupportedDocumentFormat(f"지원하지 않는 파일 형식입니다: {suffix}")

    if suffix in {".txt", ".md"}:
        content = document_path.read_text(encoding="utf-8")
    else:
        content = _read_docx(document_path)

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return content, suffix.removeprefix("."), digest


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as error:
        raise RuntimeError("docx 파일을 읽으려면 python-docx가 필요합니다.") from error

    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())


def split_chunks(content: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in content.splitlines() if paragraph.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = min(start + max_chars, len(paragraph))
            chunks.append(paragraph[start:end])
            start = max(end - overlap, end)
        current = ""
    if current:
        chunks.append(current)
    return chunks
