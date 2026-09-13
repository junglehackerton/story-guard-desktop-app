from pathlib import Path

from backend.app.services.rag import RagService
from backend.app.services.embedding_models import is_gemma_model


def test_gemma_model_selection_accepts_logical_name_and_path() -> None:
    assert is_gemma_model("embeddinggemma-300m")
    assert is_gemma_model("/tmp/models/embeddinggemma-300m")
    assert not is_gemma_model("Qwen3-Embedding-0.6B-Q8_0.gguf")


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


def test_rag_chunks_stay_within_safe_character_budget(tmp_path: Path) -> None:
    rag = RagService(tmp_path / "chroma")
    text = " ".join(["한국어 원고의 관계 근거를 확인한다."] * 120)
    chunks = rag.split_text(text, document_id=1, project_id=1)
    assert len(chunks) > 1
    assert max(len(chunk.text) for chunk in chunks) <= 520


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


class TinyEmbeddings:
    def __init__(self, model, **kwargs):
        self.model = model
    def identity(self):
        import hashlib
        return hashlib.sha256(self.model.encode()).hexdigest()[:24]
    def embed_documents(self, texts):
        return [[1.0, float('계약' in text), float('편지' in text)] for text in texts]
    def embed_query(self, text):
        return self.embed_documents([text])[0]


def test_persistent_index_is_idempotent_and_model_isolated(tmp_path, monkeypatch):
    from backend.app.services import rag as module
    monkeypatch.setattr(module, 'LocalLlmEmbeddings', TinyEmbeddings)
    first = RagService(tmp_path, embedding_model='model-a')
    first.index_chunks(1, [10], ['계약 규칙'], document_id=3, chapter_index=1)
    first.index_chunks(1, [10], ['계약 규칙'], document_id=3, chapter_index=1)
    restarted = RagService(tmp_path, embedding_model='model-a')
    assert len(restarted.retrieve(1, '계약', limit=5)) == 1
    assert restarted.retrieve(1, '계약')[0]['chunk_id'] == 10
    other = RagService(tmp_path, embedding_model='model-b')
    assert other.retrieve(1, '계약') == []


def test_retrieve_can_reuse_prepared_index_without_resync(tmp_path, monkeypatch):
    from backend.app.services import rag as module
    from types import SimpleNamespace
    monkeypatch.setattr(module, 'LocalLlmEmbeddings', TinyEmbeddings)
    rows = [{'id': 1, 'document_id': 3, 'chunk_index': 0, 'text': '계약 규칙'}]
    repo = SimpleNamespace(list_chunks=lambda _: rows, list_documents=lambda _: [SimpleNamespace(id=3, chapter_index=0)])
    rag = RagService(tmp_path, embedding_model='model-a', repository=repo)
    rag.sync_project(1)
    called = []
    original = rag.sync_project
    monkeypatch.setattr(rag, 'sync_project', lambda *args, **kwargs: called.append(True) or original(*args, **kwargs))
    assert rag.retrieve(1, '계약', ensure_index=False)
    assert called == []


def test_query_failure_reuses_stored_vectors_before_repository_reembedding(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.app.services import rag as module

    calls = []
    class Counting(TinyEmbeddings):
        def embed_documents(self, texts):
            calls.extend(texts)
            return super().embed_documents(texts)

    class StoredCollection:
        def count(self):
            return 2
        def query(self, **kwargs):
            raise RuntimeError('ONNX embedding symbol is unavailable')
        def get(self, **kwargs):
            return {
                'documents': ['계약 규칙', '편지 기록'],
                'metadatas': [
                    {'chunk_id': 1, 'document_id': 3, 'chapter_index': 0, 'chunk_index': 0},
                    {'chunk_id': 2, 'document_id': 3, 'chapter_index': 0, 'chunk_index': 1},
                ],
                'embeddings': [[1.0, 1.0, 0.0], [1.0, 0.0, 1.0]],
            }

    monkeypatch.setattr(module, 'LocalLlmEmbeddings', Counting)
    repo = SimpleNamespace(
        list_chunks=lambda _: [
            {'id': 1, 'document_id': 3, 'chunk_index': 0, 'text': '계약 규칙'},
            {'id': 2, 'document_id': 3, 'chunk_index': 1, 'text': '편지 기록'},
        ],
        list_documents=lambda _: [SimpleNamespace(id=3, chapter_index=0)],
    )
    rag = RagService(tmp_path, embedding_model='model-a', repository=repo)
    rag._read_marker = lambda _: {'embedding_identity': rag.embeddings.identity()}
    rag._collection = lambda _: StoredCollection()

    result = rag.retrieve(1, '계약', limit=1, ensure_index=False)

    assert result[0]['chunk_id'] == 1
    # Only the query is embedded; stored manuscript chunks are reused.
    assert calls == ['계약']


def test_sync_rebuilds_changed_deleted_and_new_model_data(tmp_path, monkeypatch):
    from backend.app.services import rag as module
    from types import SimpleNamespace
    monkeypatch.setattr(module, 'LocalLlmEmbeddings', TinyEmbeddings)
    rows = [{'id': 1, 'document_id': 3, 'chunk_index': 0, 'text': '계약 거절'}]
    repo = SimpleNamespace(list_chunks=lambda _: rows, list_documents=lambda _: [SimpleNamespace(id=3, chapter_index=2)])
    rag = RagService(tmp_path, embedding_model='a', repository=repo)
    assert rag.retrieve(1, '계약')[0]['text'] == '계약 거절'
    rows[0]['text'] = '계약 성립'
    assert rag.retrieve(1, '계약')[0]['text'] == '계약 성립'
    other = RagService(tmp_path, embedding_model='b', repository=repo)
    assert other.retrieve(1, '계약')[0]['text'] == '계약 성립'
    rows.clear()
    assert other.retrieve(1, '계약') == []


def test_index_rejects_mismatched_chunk_ids(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        RagService(tmp_path).index_chunks(1, [1], ['a', 'b'])


def test_append_and_revision_embed_only_changed_chunks(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.app.services import rag as module
    calls = []
    class Counting(TinyEmbeddings):
        def embed_documents(self, texts):
            calls.extend(texts)
            return super().embed_documents(texts)
    monkeypatch.setattr(module, 'LocalLlmEmbeddings', Counting)
    rows = [{'id':1,'document_id':3,'chunk_index':0,'text':'기존 계약'}]
    repo = SimpleNamespace(list_chunks=lambda _: rows, list_documents=lambda _:[SimpleNamespace(id=3,chapter_index=0)])
    rag = RagService(tmp_path, embedding_model='a', repository=repo)
    rag.sync_project(1)
    calls.clear()
    rows.append({'id':2,'document_id':3,'chunk_index':1,'text':'새로운 편지'})
    rag.sync_project(1)
    assert calls == ['새로운 편지']
    calls.clear()
    rows[0]['text'] = '수정된 계약'
    rag.sync_project(1)
    assert calls == ['수정된 계약']
    rows.pop()
    calls.clear()
    rag.sync_project(1)
    assert calls == []
    assert rag._collection(1).get()['documents'] == ['수정된 계약']


def test_markerless_rebuild_does_not_replace_already_migrated_chunks(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.app.services import rag as module
    monkeypatch.setattr(module, 'LocalLlmEmbeddings', TinyEmbeddings)
    rows = [{'id': 1, 'document_id': 3, 'chunk_index': 0, 'text': '짧은 원고 청크'}]
    replacements = []

    def replace_chunks(*args, **kwargs):
        replacements.append(True)

    repo = SimpleNamespace(
        list_chunks=lambda _: rows,
        list_documents=lambda _: [SimpleNamespace(id=3, chapter_index=0)],
        replace_chunks=replace_chunks,
    )
    rag = RagService(tmp_path, embedding_model='a', repository=repo)
    rag.sync_project(1)
    rag._index_marker(1).unlink()
    rag.sync_project(1)
    assert replacements == []
