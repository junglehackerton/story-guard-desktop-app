"""Measure real EmbeddingGemma indexing for a long manuscript on this device."""
from __future__ import annotations

import json
import os
import resource
import sys
import tempfile
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from backend.app.database import Database
from backend.app.repository import StoryRepository
from backend.app.services.embedding_models import GEMMA_MODEL, GemmaEmbeddings
from backend.app.services.rag import RagService

episodes = int(os.getenv("STORYGUARD_BENCH_EPISODES", "10"))
chars_per_episode = int(os.getenv("STORYGUARD_BENCH_CHARS_PER_EPISODE", "50000"))
base = "유나는 새벽의 항구에서 봉인된 기록을 펼쳤다. 도윤은 계약 조건을 확인했고 경비대는 종루를 지켰다. "


def usage_snapshot() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    # macOS reports bytes while Linux reports KiB.
    rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    child_rss_bytes = children.ru_maxrss if sys.platform == "darwin" else children.ru_maxrss * 1024
    return {
        "max_rss_mb": round(rss_bytes / (1024 * 1024), 1),
        "max_child_rss_mb": round(child_rss_bytes / (1024 * 1024), 1),
        "user_cpu_seconds": round(usage.ru_utime, 3),
        "system_cpu_seconds": round(usage.ru_stime, 3),
        "child_user_cpu_seconds": round(children.ru_utime, 3),
        "child_system_cpu_seconds": round(children.ru_stime, 3),
    }

with tempfile.TemporaryDirectory(prefix="storyguard-gemma-long-") as directory:
    data_dir = Path(directory)
    # Point the application model resolver at a temporary data root while
    # reusing the already downloaded benchmark model (no model copy).
    os.environ["STORY_GUARD_DATA_DIR"] = str(data_dir)
    (data_dir / "models").mkdir()
    (data_dir / "models" / GEMMA_MODEL).symlink_to(
        root / ".cache/embedding-bench-models" / GEMMA_MODEL,
        target_is_directory=True,
    )
    repo = StoryRepository(Database(data_dir / "story.sqlite"))
    project = repo.create_project("EmbeddingGemma 장편 색인")
    splitter = RagService.__new__(RagService)
    for index in range(episodes):
        content = (base * ((chars_per_episode // len(base)) + 1))[:chars_per_episode]
        document = repo.add_document(project.id, data_dir / f"{index + 1}.txt", f"{index + 1}화", "txt", str(index), content, index)
        chunks = splitter.split_text(content, document.id, project.id)
        repo.replace_chunks(project.id, document.id, [chunk.text for chunk in chunks])

    rag = RagService(data_dir / "chroma", embedding_model=GEMMA_MODEL, repository=repo)
    started = time.perf_counter()
    indexed = rag.sync_project(project.id)
    elapsed = time.perf_counter() - started
    # Append one full-sized episode and measure the incremental path. Existing
    # vectors must be reused; only the new document's chunks should be sent to
    # the embedding worker.
    appended_content = (base * ((chars_per_episode // len(base)) + 1))[:chars_per_episode]
    appended = repo.add_document(project.id, data_dir / f'{episodes + 1}.txt', f'{episodes + 1}화', 'txt', str(episodes), appended_content, episodes)
    appended_chunks = splitter.split_text(appended_content, appended.id, project.id)
    repo.replace_chunks(project.id, appended.id, [chunk.text for chunk in appended_chunks])
    append_started = time.perf_counter()
    append_indexed = rag.sync_project(project.id)
    append_elapsed = time.perf_counter() - append_started
    # The Gemma adapter runs in an isolated child process. Reap it before
    # reading RUSAGE_CHILDREN so the report includes the worker's peak RSS.
    GemmaEmbeddings._cleanup_workers()
    usage = usage_snapshot()
    result = {
        "episodes": episodes,
        "chars": episodes * chars_per_episode,
        "chunks": indexed,
        "index_seconds": round(elapsed, 3),
        "chunks_per_second": round(indexed / elapsed, 3) if elapsed else None,
        "appended_episode": episodes + 1,
        "appended_chunks": len(appended_chunks),
        "append_index_seconds": round(append_elapsed, 3),
        "append_chunks_per_second": round(len(appended_chunks) / append_elapsed, 3) if append_elapsed else None,
        "append_indexed_total": append_indexed,
        **usage,
        "model": "EmbeddingGemma 300M",
        "scope": "실제 Gemma 워커·Chroma 색인; GPT 분석 품질·제공자 지연 제외",
    }
    output = root / "output/validation/realistic-manuscript-20260912/gemma-long-index.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
