"""Measure the local long-manuscript path with a real Gemma index.

The external GPT provider is stubbed to avoid spending a user's quota. This
still exercises parsing, Gemma indexing, retrieval, window checkpoints, and
the analyzer's prepared-index reuse contract together.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from backend.app.database import Database
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.embedding_models import GEMMA_MODEL, GemmaEmbeddings
from backend.app.services.rag import RagService


BASE = "유나는 안개 낀 항구에서 봉인된 기록을 펼쳤다. 도윤은 계약 조건을 확인했고 경비대는 종루를 지켰다. "


class CountingConnection:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        return {"text": '{"entities": [], "relations": [], "issues": []}'}


with tempfile.TemporaryDirectory(prefix="storyguard-local-analysis-") as directory:
    data_dir = Path(directory)
    import os

    os.environ["STORY_GUARD_DATA_DIR"] = str(data_dir)
    (data_dir / "models").mkdir()
    (data_dir / "models" / GEMMA_MODEL).symlink_to(
        root / ".cache/embedding-bench-models" / GEMMA_MODEL,
        target_is_directory=True,
    )
    repo = StoryRepository(Database(data_dir / "story.sqlite"))
    project = repo.create_project("로컬 통합 장편 검증")
    splitter = RagService.__new__(RagService)
    for index in range(10):
        content = (BASE * 2000)[:10000]
        document = repo.add_document(project.id, data_dir / f"{index + 1}.txt", f"{index + 1}화", "txt", str(index), content, index)
        chunks = splitter.split_text(content, document.id, project.id)
        repo.replace_chunks(project.id, document.id, [chunk.text for chunk in chunks])

    rag = RagService(data_dir / "chroma", embedding_model=GEMMA_MODEL, repository=repo)
    connection = CountingConnection()
    started = time.perf_counter()
    result = GptStoryAnalyzer(repo, rag, connection).analyze(project.id, GEMMA_MODEL, "low")
    elapsed = time.perf_counter() - started
    job = repo.latest_analysis_job(project.id)
    report = {
        "episodes": 10,
        "chars_per_episode": 10000,
        "total_chars": 100000,
        "chunks": len(repo.list_chunks(project.id)),
        "provider_stub_calls": connection.calls,
        "status": job.status.value,
        "analysis_seconds": round(elapsed, 3),
        "failed_windows": result["failed_window_count"],
        "scope": "실제 EmbeddingGemma 색인·검색과 GPT 오케스트레이터 통합 경로; 외부 GPT 품질·지연 제외",
    }
    output = root / "output/validation/realistic-manuscript-20260912/local-analysis.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
