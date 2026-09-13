from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math
import threading
import time

from backend.app.services.embedding_models import GEMMA_MODEL, GemmaEmbeddings, is_gemma_model
from backend.app.services.hybrid_search import lexical_rank, merge_rankings
from backend.app.services.local_ai import DEFAULT_EMBEDDING_MODEL, LocalLlmEmbeddings


class _StoredVectorEmbeddingFunction:
    """Prevent Chroma from constructing its optional default ONNX model.

    Story Guard computes vectors before writing/querying Chroma, so Chroma's
    embedding callback is never used. Passing an explicit callback is still
    necessary on installations where the optional ONNX dependency is absent;
    otherwise Chroma tries to resolve ``ONNXMiniLM_L6_V2`` while opening an
    existing collection and the whole GPT analysis fails before retrieval.
    """

    def __call__(self, input: list[str]) -> list[list[float]]:
        # This path is intentionally unused because all callers provide
        # embeddings explicitly. Keep a valid callback for Chroma's protocol.
        return [[0.0] for _ in input]


@dataclass
class RagChunk:
    text: str
    metadata: dict[str, int | str]


class RagService:
    _lock = threading.RLock()

    def __init__(
        self,
        persist_dir: Path,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        repository=None,
    ) -> None:
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.repository = repository
        self.embeddings = GemmaEmbeddings() if is_gemma_model(embedding_model) else LocalLlmEmbeddings(model=embedding_model)
        self.persist_dir.mkdir(parents=True, exist_ok=True)

    def split_text(self, text: str, document_id: int, project_id: int) -> list[RagChunk]:
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except ImportError:
            return self._fallback_split(text, document_id, project_id)

        # Keep Korean chunks below llama.cpp's conservative 512-token batch
        # limit across packaged runtime versions. Character counts are not
        # token counts: Qwen's Korean tokenizer can produce roughly 1.5–2
        # tokens per character, so a 420-character chunk can still request
        # 600+ tokens and fail before embedding. A smaller chunk preserves
        # the full text (no truncation) while keeping long manuscripts safe.
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=480,
            chunk_overlap=48,
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

    def _collection_name(self, project_id: int) -> str:
        return f"project_{project_id}_{self.embeddings.identity()}"

    def _client(self):
        # Chroma 0.5.x lazily resolves its ONNX default embedding symbol.
        # PyInstaller can omit that optional module, leaving the symbol
        # undefined even when every vector is supplied by Story Guard.
        try:
            import chromadb.utils.embedding_functions as embedding_functions
            if not hasattr(embedding_functions, "ONNXMiniLM_L6_V2"):
                embedding_functions.ONNXMiniLM_L6_V2 = _StoredVectorEmbeddingFunction
        except ImportError:
            pass
        # Patch the symbol before importing chromadb itself: chromadb's client
        # evaluates DefaultEmbeddingFunction() in a function default at import
        # time, so patching after ``import chromadb`` is too late in a frozen app.
        import chromadb
        from chromadb.config import Settings
        try:
            return chromadb.PersistentClient(
                path=str(self.persist_dir), settings=Settings(anonymized_telemetry=False))
        except Exception as error:
            # A partially written HNSW/SQLite index must not block every new
            # analysis. Preserve it for diagnosis and rebuild a clean index.
            if not self._is_corrupt_index_error(error):
                raise
            self._quarantine_corrupt_index()
            return chromadb.PersistentClient(
                path=str(self.persist_dir), settings=Settings(anonymized_telemetry=False))

    @staticmethod
    def _is_corrupt_index_error(error: Exception) -> bool:
        message = str(error).lower()
        return "decompress" in message or "header check" in message

    def _quarantine_corrupt_index(self) -> Path:
        """Preserve a broken Chroma store and return its quarantine path."""
        backup = self.persist_dir.with_name(
            f"{self.persist_dir.name}-corrupt-{time.time_ns()}"
        )
        if self.persist_dir.exists():
            self.persist_dir.rename(backup)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        return backup

    def _collection(self, project_id: int):
        client = self._client()
        try:
            return client.get_or_create_collection(
                name=self._collection_name(project_id),
                embedding_function=_StoredVectorEmbeddingFunction(),
                metadata={"hnsw:space": "cosine", "embedding_model": self.embedding_model,
                          "embedding_identity": self.embeddings.identity()})
        except Exception as error:
            if not self._is_corrupt_index_error(error):
                raise
            self._quarantine_corrupt_index()
            return self._client().get_or_create_collection(
                name=self._collection_name(project_id),
                embedding_function=_StoredVectorEmbeddingFunction(),
                metadata={"hnsw:space": "cosine", "embedding_model": self.embedding_model,
                          "embedding_identity": self.embeddings.identity()})

    def index_chunks(
        self, project_id: int, chunk_ids: list[int], chunks: list[str],
        document_id: int | None = None, chapter_index: int | None = None,
        chunk_indexes: list[int] | None = None,
    ) -> int:
        if len(chunk_ids) != len(chunks) or len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("청크 ID와 원문 수가 일치하고 ID가 고유해야 합니다.")
        if not chunks:
            return 0
        with self._lock:
            rows = [{
                "id": chunk_id, "text": text,
                "document_id": document_id or 0,
                "chapter_index": chapter_index if chapter_index is not None else -1,
                "chunk_index": chunk_indexes[i] if chunk_indexes is not None else i,
            } for i, (chunk_id, text) in enumerate(zip(chunk_ids, chunks))]
            self._upsert_rows(project_id, rows)
            self._write_marker(project_id, {"embedding_identity": self.embeddings.identity()})
        return len(chunks)

    def _upsert_rows(self, project_id: int, rows: list[dict], progress=None) -> int:
        """Embed and upsert pending rows in bounded batches.

        Keeping the model context and Chroma collection alive across batches is
        materially faster for multi-chapter manuscripts than reopening them
        once per document. The 16-row batch remains conservative for laptops.
        """
        if not rows:
            return 0
        collection = self._collection(project_id)
        total = len(rows)
        for start in range(0, total, 16):
            batch = rows[start:start + 16]
            vectors = self.embeddings.embed_documents([row["text"] for row in batch])
            collection.upsert(
                ids=[str(row["id"]) for row in batch],
                documents=[row["text"] for row in batch],
                embeddings=vectors,
                metadatas=[{
                    "project_id": project_id,
                    "chunk_id": row["id"],
                    "document_id": row.get("document_id", 0),
                    "chapter_index": row.get("chapter_index", -1),
                    "chunk_index": row.get("chunk_index", index),
                } for index, row in enumerate(batch)],
            )
            if progress:
                progress(min(start + len(batch), total), total)
        return len(rows)

    def sync_project(self, project_id: int, progress=None) -> int:
        """Rebuild derived vectors when the persisted source or embedding model changes."""
        if self.repository is None:
            raise RuntimeError("인덱스 재구성에 원고 저장소가 필요합니다.")
        with self._lock:
            rows = self.repository.list_chunks(project_id)
            # Chunks are persisted at import time. Projects imported by an
            # older build may still contain 900-character rows that exceed
            # the bundled embedding model's 512-token batch. Migrate those
            # rows from the canonical document text before embedding instead
            # of asking the user to delete and re-import every episode.
            marker = self._read_marker(project_id) or {}
            # A missing marker is normal when a derived index is being rebuilt
            # (for example after corruption quarantine). Do not migrate the
            # canonical chunks on every retrieval in that state: replacing
            # chunks changes their IDs and makes an in-flight GPT run report
            # a false "manuscript changed" error. Only an existing, older
            # marker requests a policy migration; marker-less stores migrate
            # solely when an actually oversized chunk is present.
            needs_policy_migration = bool(marker) and marker.get("chunk_policy") != "480-v1" and hasattr(self.repository, "replace_chunks")
            if any(len(str(row.get("text", ""))) > 520 for row in rows) or needs_policy_migration:
                from backend.app.services.parser import split_chunks

                for document in self.repository.list_documents(project_id):
                    self.repository.replace_chunks(
                        project_id,
                        document.id,
                        split_chunks(document.content),
                    )
                rows = self.repository.list_chunks(project_id)
            chapters = {doc.id: doc.chapter_index for doc in self.repository.list_documents(project_id)}
            snapshot = [{**row, "chapter_index": chapters.get(row["document_id"], -1)} for row in rows]
            signature = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            expected = {"embedding_identity": self.embeddings.identity(), "source_signature": signature,
                        "chunk_policy": "480-v1"}
            if self._read_marker(project_id) == expected:
                if self._collection(project_id).count() == len(rows):
                    return len(rows)
            # Incomplete rebuilds never receive a valid source signature and retry next time.
            self._index_marker(project_id).unlink(missing_ok=True)
            collection = self._collection(project_id)
            try:
                stored = collection.get(include=["documents", "metadatas"])
            except Exception as error:
                # HNSW can be corrupted after the client and collection have
                # opened successfully (for example after an interrupted
                # native write). Preserve it and rebuild from SQLite rows.
                if not self._is_corrupt_index_error(error):
                    raise
                self._quarantine_corrupt_index()
                collection = self._collection(project_id)
                stored = {"ids": [], "documents": [], "metadatas": []}
            existing = {key: (text, metadata) for key, text, metadata in
                        zip(stored['ids'], stored['documents'], stored['metadatas'])}
            wanted = {str(row['id']) for row in rows}
            stale = list(set(existing) - wanted)
            if stale:
                collection.delete(ids=stale)
            pending_rows: list[dict] = []
            for document_id, chapter in chapters.items():
                document_rows = []
                for row in rows:
                    if row['document_id'] != document_id:
                        continue
                    previous = existing.get(str(row['id']))
                    if previous is not None and previous[0] == row['text'] and all(
                        previous[1].get(key) == value for key, value in {
                            'document_id': document_id, 'chapter_index': chapter,
                            'chunk_index': row['chunk_index'], 'project_id': project_id}.items()):
                        continue
                    document_rows.append(row)
                if document_rows:
                    pending_rows.extend({
                        "id": row["id"], "text": row["text"],
                        "document_id": document_id, "chapter_index": chapter,
                        "chunk_index": row["chunk_index"],
                    } for row in document_rows)
            self._upsert_rows(project_id, pending_rows, progress=progress)
            self._write_marker(project_id, expected)
            return len(rows)

    def retrieve(
        self, project_id: int, query: str, limit: int = 4,
        start_chapter: int | None = None, end_chapter: int | None = None,
        strategy: str = "dense", ensure_index: bool = True,
    ) -> list[dict]:
        if strategy not in {"dense", "hybrid"}:
            raise ValueError("Unknown retrieval strategy")
        if limit <= 0:
            return []
        with self._lock:
            if self.repository is not None and ensure_index:
                try:
                    self.sync_project(project_id)
                except Exception as error:
                    if self.repository is not None:
                        return self._repository_retrieve(project_id, query, limit,
                                                         start_chapter, end_chapter, strategy)
                    raise
            if not self._read_marker(project_id):
                return []
            try:
                collection = self._collection(project_id)
            except Exception:
                if self.repository is not None:
                    return self._repository_retrieve(project_id, query, limit,
                                                     start_chapter, end_chapter, strategy)
                raise
            try:
                count = collection.count()
            except Exception as error:
                # A damaged HNSW index can open successfully but fail on the
                # first count/query. Fall back to SQLite-backed retrieval so
                # one corrupt derived cache never aborts GPT analysis.
                if self.repository is None:
                    raise
                if self._is_corrupt_index_error(error):
                    self._quarantine_corrupt_index()
                return self._repository_retrieve(project_id, query, limit,
                                                 start_chapter, end_chapter, strategy)
            if not count:
                return []
            query_vector = self.embeddings.embed_query(query)
            try:
                result = collection.query(
                    query_embeddings=[query_vector],
                    n_results=min(max(limit, 8) if strategy == "hybrid" else limit, count),
                    where=self._range_filter(start_chapter, end_chapter),
                    include=["documents", "metadatas"],
                )
            except Exception as error:
                # Some frozen Chroma builds omit the optional ONNX symbol and
                # fail while entering query(), even though explicit vectors
                # are supplied. Read the stored vectors and rank locally so a
                # packaged desktop app keeps working without that dependency.
                if self.repository is None:
                    raise
                try:
                    # The index was already built and contains the vectors we
                    # need. Reusing them avoids re-embedding every chunk of a
                    # long manuscript on each retrieval fallback.
                    return self._manual_retrieve(collection, query_vector, query, limit,
                                                 start_chapter, end_chapter, strategy)
                except Exception as manual_error:
                    # A genuinely damaged store may also fail to expose its
                    # vectors. Only then fall back to the repository path,
                    # which can rebuild vectors from canonical SQLite text.
                    if self._is_corrupt_index_error(manual_error):
                        self._quarantine_corrupt_index()
                    return self._repository_retrieve(project_id, query, limit,
                                                     start_chapter, end_chapter, strategy)
            dense = [{"text": text, **metadata} for text, metadata in
                     zip(result["documents"][0], result["metadatas"][0])]
            if strategy == "dense":
                return dense
            try:
                stored = collection.get(where=self._range_filter(start_chapter, end_chapter),
                                        include=["documents", "metadatas"])
            except Exception as error:
                # Hybrid retrieval reads the lexical candidate set after the
                # dense query. Treat this read as another derived-cache
                # boundary: a damaged HNSW/SQLite cache must not turn an
                # otherwise recoverable analysis into a hard failure.
                if self.repository is None:
                    raise
                if self._is_corrupt_index_error(error):
                    self._quarantine_corrupt_index()
                return self._repository_retrieve(project_id, query, limit,
                                                 start_chapter, end_chapter, strategy)
            rows = [{"text": text, **metadata} for text, metadata in
                    zip(stored["documents"], stored["metadatas"])]
            lexical = lexical_rank(rows, query)
            merged = merge_rankings(dense, lexical, limit)
            return self._protect_canonical_lexical(project_id, query, limit,
                                                   start_chapter, end_chapter, merged)

    def _manual_retrieve(
        self, collection, query_vector: list[float], query: str, limit: int,
        start_chapter: int | None, end_chapter: int | None, strategy: str,
    ) -> list[dict]:
        stored = collection.get(
            where=self._range_filter(start_chapter, end_chapter),
            include=["documents", "metadatas", "embeddings"],
        )
        query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
        ranked = []
        for text, metadata, vector in zip(
            stored.get("documents", []), stored.get("metadatas", []),
            stored.get("embeddings", []),
        ):
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            score = sum(a * b for a, b in zip(query_vector, vector)) / (query_norm * norm)
            ranked.append((score, {"text": text, **metadata}))
        dense = [row for _, row in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]]
        if strategy == "dense":
            return dense
        rows = [{"text": text, **metadata} for text, metadata in zip(
            stored.get("documents", []), stored.get("metadatas", []))]
        merged = merge_rankings(dense, lexical_rank(rows, query), limit)
        return self._protect_canonical_lexical(project_id, query, limit,
                                               start_chapter, end_chapter, merged)

    def _protect_canonical_lexical(
        self, project_id: int, query: str, limit: int,
        start_chapter: int | None, end_chapter: int | None,
        merged: list[dict],
    ) -> list[dict]:
        """Keep current SQLite lexical evidence in top-k during index lag."""
        if self.repository is None or not merged:
            return merged[:limit]
        chapters = {doc.id: doc.chapter_index for doc in self.repository.list_documents(project_id)}
        rows = []
        for row in self.repository.list_chunks(project_id):
            chapter = chapters.get(row['document_id'], -1)
            if ((start_chapter is None or chapter >= start_chapter) and
                    (end_chapter is None or chapter <= end_chapter)):
                rows.append({"text": row["text"], "chunk_id": row["id"],
                             "document_id": row["document_id"], "chapter_index": chapter,
                             "chunk_index": row.get("chunk_index", 0), "project_id": project_id})
        canonical = lexical_rank(rows, query)[:max(1, limit // 2)]
        present = {str(row['chunk_id']) for row in merged}
        for candidate in canonical:
            key = str(candidate['chunk_id'])
            existing_index = next((i for i, row in enumerate(merged)
                                   if str(row['chunk_id']) == key), None)
            # Replace stale metadata for an ID that Chroma returned from an
            # older source snapshot; the canonical row has the current text
            # and chapter location used by the evidence validator.
            if existing_index is not None:
                merged[existing_index] = candidate
            elif merged:
                merged[-1] = candidate
                present.add(key)
        # Put the strongest current lexical evidence first. This guarantees
        # that a precise rule/entity mention remains visible even when dense
        # similarity is dominated by repeated filler chapters.
        if canonical:
            canonical_ids = {str(row['chunk_id']) for row in canonical}
            merged = canonical + [row for row in merged if str(row['chunk_id']) not in canonical_ids]
        return merged[:limit]

    def _repository_retrieve(
        self, project_id: int, query: str, limit: int,
        start_chapter: int | None, end_chapter: int | None, strategy: str,
    ) -> list[dict]:
        """Portable retrieval fallback for frozen builds missing Chroma's ONNX symbol."""
        rows = self.repository.list_chunks(project_id) if self.repository is not None else []
        chapters = {doc.id: doc.chapter_index for doc in self.repository.list_documents(project_id)} if self.repository is not None else {}
        rows = [row for row in rows if (start_chapter is None or chapters.get(row['document_id'], -1) >= start_chapter)
                and (end_chapter is None or chapters.get(row['document_id'], -1) <= end_chapter)]
        if not rows:
            return []
        query_vector = self.embeddings.embed_query(query)
        vectors = self.embeddings.embed_documents([row['text'] for row in rows])
        query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
        ranked = []
        for row, vector in zip(rows, vectors):
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            score = sum(a * b for a, b in zip(query_vector, vector)) / (query_norm * norm)
            ranked.append((score, {"text": row['text'], "chunk_id": row['id'], **row,
                                    "chapter_index": chapters.get(row['document_id'], -1)}))
        dense = [row for _, row in sorted(ranked, key=lambda item: item[0], reverse=True)[:limit]]
        if strategy == "dense":
            return dense
        lexical_rows = [{"text": row['text'], "chunk_id": row['id'], **row,
                         "chapter_index": chapters.get(row['document_id'], -1)} for row in rows]
        merged = merge_rankings(dense, lexical_rank(lexical_rows, query), limit)
        return self._protect_canonical_lexical(project_id, query, limit,
                                               start_chapter, end_chapter, merged)

    def delete_project_index(self, project_id: int) -> None:
        with self._lock:
            client = self._client()
            prefix = f"project_{project_id}_"
            for collection in client.list_collections():
                name = collection if isinstance(collection, str) else collection.name
                if name == f"project_{project_id}" or name.startswith(prefix):
                    client.delete_collection(name)
            for marker in self.persist_dir.glob(f"project_{project_id}_*.indexed"):
                marker.unlink(missing_ok=True)
            (self.persist_dir / f"project_{project_id}.indexed").unlink(missing_ok=True)

    def _index_marker(self, project_id: int) -> Path:
        return self.persist_dir / f"{self._collection_name(project_id)}.indexed"

    def _read_marker(self, project_id: int) -> dict:
        try:
            data = json.loads(self._index_marker(project_id).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def _write_marker(self, project_id: int, data: dict) -> None:
        marker = self._index_marker(project_id)
        partial = marker.with_suffix(".tmp")
        partial.write_text(json.dumps(data), encoding="utf-8")
        partial.replace(marker)

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
        max_chars = 480
        overlap = 48
        def append_piece(piece: str) -> None:
            if piece.strip():
                chunks.append(RagChunk(text=piece.strip(), metadata={"document_id": document_id, "project_id": project_id}))
        for paragraph in paragraphs:
            candidate = f"{current}\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                append_piece(current)
            # A single paragraph can exceed the safe token budget. Slice it
            # with a small overlap so no content is silently truncated.
            while len(paragraph) > max_chars:
                append_piece(paragraph[:max_chars])
                paragraph = paragraph[max_chars - overlap:]
            current = paragraph
        if current:
            append_piece(current)
        return chunks
