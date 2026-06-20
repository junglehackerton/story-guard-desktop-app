from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class RagChunk:
    text: str
    metadata: dict[str, int | str]


class OllamaLangChainEmbeddings:
    """LangChain-compatible local embedding adapter backed by Ollama."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434/api",
        model: str = "embeddinggemma",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embed([text])
        if not vectors:
            raise RuntimeError("Ollama returned no embedding for query")
        return vectors[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{self.base_url}/embed",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
        return payload.get("embeddings", [])


class RagService:
    def __init__(
        self,
        persist_dir: Path,
        embedding_model: str = "embeddinggemma",
        ollama_base_url: str = "http://localhost:11434/api",
    ) -> None:
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.ollama_base_url = ollama_base_url
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

    def index_chunks(self, project_id: int, chunk_ids: list[int], chunks: list[str]) -> int:
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
                metadata={"project_id": project_id, "chunk_id": chunk_id},
            )
            for chunk_id, text in zip(chunk_ids, chunks)
        ]
        Chroma.from_documents(
            documents=documents,
            embedding=OllamaLangChainEmbeddings(
                base_url=self.ollama_base_url,
                model=self.embedding_model,
            ),
            collection_name=f"project_{project_id}",
            persist_directory=str(self.persist_dir),
            client_settings=Settings(anonymized_telemetry=False),
        )
        self._index_marker(project_id).write_text("indexed", encoding="utf-8")
        return len(documents)

    def retrieve(self, project_id: int, query: str, limit: int = 4) -> list[dict]:
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
            embedding_function=OllamaLangChainEmbeddings(
                base_url=self.ollama_base_url,
                model=self.embedding_model,
            ),
            client_settings=Settings(anonymized_telemetry=False),
        )
        docs = store.similarity_search(query, k=limit)
        return [
            {
                "text": doc.page_content,
                "chunk_id": int(doc.metadata.get("chunk_id", 0)),
                "project_id": int(doc.metadata.get("project_id", project_id)),
            }
            for doc in docs
        ]

    def _index_marker(self, project_id: int) -> Path:
        return self.persist_dir / f"project_{project_id}.indexed"

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
