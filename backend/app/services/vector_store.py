from __future__ import annotations

from pathlib import Path


class _StoredVectorEmbeddingFunction:
    """Keep Chroma from loading its optional ONNX default embedding model."""

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [[0.0] for _ in input]


class VectorIndex:
    def __init__(self, persist_dir: Path) -> None:
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)

    def available(self) -> bool:
        try:
            import chromadb  # noqa: F401
        except ImportError:
            return False
        return True

    def upsert_texts(
        self,
        project_id: int,
        chunk_ids: list[int],
        texts: list[str],
        embeddings: list[list[float]],
    ) -> int:
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            return 0
        if not texts or len(texts) != len(embeddings):
            return 0

        client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(
            name=f"project_{project_id}",
            embedding_function=_StoredVectorEmbeddingFunction(),
        )
        collection.upsert(
            ids=[str(chunk_id) for chunk_id in chunk_ids],
            documents=texts,
            embeddings=embeddings,
            metadatas=[{"project_id": project_id, "chunk_id": chunk_id} for chunk_id in chunk_ids],
        )
        return len(texts)

    def query(self, project_id: int, text: str, limit: int = 5) -> list[str]:
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            return []

        client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(
            name=f"project_{project_id}",
            embedding_function=_StoredVectorEmbeddingFunction(),
        )
        # This legacy index does not retain an embedding model. Return no
        # semantic results rather than asking Chroma to construct its ONNX
        # default model at runtime.
        result = collection.get(limit=limit)
        documents = result.get("documents", [[]])
        return [str(document) for document in documents[0]]
