from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.services.local_ai import DEFAULT_EMBEDDING_MODEL, LocalLlmEmbeddings


@dataclass
class RagChunk:
    text: str
    metadata: dict[str, int | str]


class RagService:
    def __init__(
        self,
        persist_dir: Path,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.persist_dir.mkdir(parents=True, exist_ok=True)

    def split_text(self, text: str, document_id: int, project_id: int) -> list[RagChunk]:
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError:
            return self._fallback_split(text, document_id, project_id)

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=900,
            chunk_overlap=120,
            separators=["\n\n", "\n", ". ", "。", "!", "?", " ", ""],
        )
        docs = splitter.create_documents(
            [text],
            metadatas=[{"document_id": document_id, "project_id": project_id}],
        )
        return [
            RagChunk(text=doc.page_content, metadata=dict(doc.metadata))
            for doc in docs
            if doc.page_content.strip()
        ]

    def index_chunks(
        self,
        project_id: int,
        chunk_ids: list[int],
        chunks: list[str],
        document_id: int | None = None,
        chapter_index: int | None = None,
        chunk_indexes: list[int] | None = None,
    ) -> int:
        if not chunks:
            return 0
        try:
            from chromadb.config import Settings
            from langchain_community.vectorstores import Chroma
            from langchain_core.documents import Document
        except ImportError:
            return 0

        documents = [
            Document(
                page_content=text,
                metadata={
                    "project_id": project_id,
                    "chunk_id": chunk_id,
                    "document_id": document_id or 0,
                    "chapter_index": chapter_index if chapter_index is not None else -1,
                    "chunk_index": chunk_indexes[index] if chunk_indexes and index < len(chunk_indexes) else index,
                },
            )
            for index, (chunk_id, text) in enumerate(zip(chunk_ids, chunks))
        ]
        Chroma.from_documents(
            documents=documents,
            embedding=LocalLlmEmbeddings(model=self.embedding_model),
            collection_name=f"project_{project_id}",
            persist_directory=str(self.persist_dir),
            client_settings=Settings(anonymized_telemetry=False),
        )
        self._index_marker(project_id).write_text("indexed", encoding="utf-8")
        return len(documents)

    def retrieve(
        self,
        project_id: int,
        query: str,
        limit: int = 4,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> list[dict]:
        if not self._index_marker(project_id).exists():
            return []
        try:
            from chromadb.config import Settings
            from langchain_community.vectorstores import Chroma
        except ImportError:
            return []

        store = Chroma(
            collection_name=f"project_{project_id}",
            persist_directory=str(self.persist_dir),
            embedding_function=LocalLlmEmbeddings(model=self.embedding_model),
            client_settings=Settings(anonymized_telemetry=False),
        )
        chroma_filter = self._range_filter(start_chapter, end_chapter)
        try:
            docs = store.similarity_search(query, k=limit, filter=chroma_filter) if chroma_filter else store.similarity_search(query, k=limit)
        except Exception:
            docs = store.similarity_search(query, k=max(limit * 3, limit))
            if start_chapter is not None or end_chapter is not None:
                docs = [
                    doc
                    for doc in docs
                    if self._in_range(int(doc.metadata.get("chapter_index", -1)), start_chapter, end_chapter)
                ]
            docs = docs[:limit]
        return [
            {
                "text": doc.page_content,
                "chunk_id": int(doc.metadata.get("chunk_id", 0)),
                "project_id": int(doc.metadata.get("project_id", project_id)),
                "document_id": int(doc.metadata.get("document_id", 0)),
                "chapter_index": int(doc.metadata.get("chapter_index", -1)),
                "chunk_index": int(doc.metadata.get("chunk_index", 0)),
            }
            for doc in docs
        ]

    def delete_project_index(self, project_id: int) -> None:
        marker = self._index_marker(project_id)
        try:
            marker.unlink()
        except FileNotFoundError:
            pass

        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            return

        client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        try:
            client.delete_collection(name=f"project_{project_id}")
        except Exception:
            return

    def _index_marker(self, project_id: int) -> Path:
        return self.persist_dir / f"project_{project_id}.indexed"

    def _range_filter(self, start_chapter: int | None, end_chapter: int | None) -> dict | None:
        filters: list[dict] = []
        if start_chapter is not None:
            filters.append({"chapter_index": {"$gte": start_chapter}})
        if end_chapter is not None:
            filters.append({"chapter_index": {"$lte": end_chapter}})
        if not filters:
            return None
        return filters[0] if len(filters) == 1 else {"$and": filters}

    def _in_range(self, chapter_index: int, start_chapter: int | None, end_chapter: int | None) -> bool:
        if start_chapter is not None and chapter_index < start_chapter:
            return False
        if end_chapter is not None and chapter_index > end_chapter:
            return False
        return True

    def _fallback_split(self, text: str, document_id: int, project_id: int) -> list[RagChunk]:
        paragraphs = [paragraph.strip() for paragraph in text.splitlines() if paragraph.strip()]
        chunks: list[RagChunk] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= 900:
                current = candidate
                continue
            if current:
                chunks.append(
                    RagChunk(
                        text=current,
                        metadata={"document_id": document_id, "project_id": project_id},
                    )
                )
            current = paragraph
        if current:
            chunks.append(
                RagChunk(
                    text=current,
                    metadata={"document_id": document_id, "project_id": project_id},
                )
            )
        return chunks
