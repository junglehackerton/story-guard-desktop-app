"""Stress the review pipeline with long web-novel-sized episodes.

The provider is deliberately stubbed so this measures chunking, checkpoint
storage, and failure isolation without spending a user's AI quota.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import os
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from backend.app.database import Database
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService

EPISODES = int(os.getenv("STORY_GUARD_BENCH_EPISODES", "10"))
CHARS_PER_EPISODE = int(os.getenv("STORY_GUARD_BENCH_CHARS", "20000"))
BASE = (
    "유나는 안개 낀 항구에서 봉인된 기록을 펼쳤다. 도윤은 계약 조건을 다시 확인했고, "
    "경비대는 검은 종루의 문을 지켰다. 새로운 단서가 다음 사건으로 이어졌다. "
)


class RagStub:
    def __init__(self, repository):
        self.repository = repository

    def sync_project(self, project_id, progress=None):
        rows = self.repository.list_chunks(project_id)
        if progress:
            progress(len(rows), len(rows))
        return len(rows)

    def retrieve(self, *args, **kwargs):
        return []


with tempfile.TemporaryDirectory(prefix="storyguard-long-episodes-") as directory:
    root_dir = Path(directory)
    repo = StoryRepository(Database(root_dir / "long.sqlite"))
    project = repo.create_project("긴 회차 스트레스 검증")
    splitter = RagService.__new__(RagService)
    for chapter in range(EPISODES):
        text = (BASE * ((CHARS_PER_EPISODE // len(BASE)) + 1))[:CHARS_PER_EPISODE]
        doc = repo.add_document(project.id, root_dir / f"{chapter + 1}.txt", f"{chapter + 1}화", "txt", str(chapter), text, chapter)
        chunks = splitter.split_text(text, doc.id, project.id)
        repo.replace_chunks(project.id, doc.id, [chunk.text for chunk in chunks])

    calls = [0]
    timeouts_injected = [0]

    def complete(model, prompt, **kwargs):
        calls[0] += 1
        # Exercise the same timeout branch used by a slow provider once; the
        # review window should split and continue with bounded sub-requests.
        if calls[0] == 1:
            timeouts_injected[0] += 1
            raise RuntimeError("response timed out")
        return {"text": '{"entities": [], "relations": [], "issues": []}'}

    started = time.monotonic()
    result = GptStoryAnalyzer(repo, RagStub(repo), SimpleNamespace(complete=complete)).analyze(
        project.id, "GPT-6.5-Luna", "medium"
    )
    elapsed = time.monotonic() - started
    # Append one more long episode and verify incremental reuse on the same
    # workload. Only the new episode's review windows should call the provider.
    appended_text = (BASE * ((CHARS_PER_EPISODE // len(BASE)) + 1))[:CHARS_PER_EPISODE]
    appended_episode = EPISODES + 1
    appended = repo.add_document(project.id, root_dir / f"{appended_episode}.txt", f"{appended_episode}화", "txt", str(appended_episode), appended_text, EPISODES)
    appended_chunks = splitter.split_text(appended_text, appended.id, project.id)
    repo.replace_chunks(project.id, appended.id, [chunk.text for chunk in appended_chunks])
    calls_before_append = calls[0]
    append_result = GptStoryAnalyzer(repo, RagStub(repo), SimpleNamespace(complete=complete)).analyze(
        project.id, "GPT-6.5-Luna", "medium"
    )
    append_calls = calls[0] - calls_before_append
    job = repo.latest_analysis_job(project.id)
    report = {
        "episodes": EPISODES,
        "chars_per_episode": CHARS_PER_EPISODE,
        "chars": EPISODES * CHARS_PER_EPISODE,
        "chunks": len(repo.list_chunks(project.id)),
        "review_windows": len(job.window_details),
        "provider_calls": calls[0],
        "timeouts_injected": timeouts_injected[0],
        "failed_windows": result["failed_window_count"],
        "status": job.status.value,
        "orchestration_seconds": round(elapsed, 3),
        "append_episode": appended_episode,
        "append_provider_calls": append_calls,
        "append_cached_windows": append_result["cached_count"],
        "append_failed_windows": append_result["failed_window_count"],
        "scope": "긴 회차의 청킹·검토 구간 생성·체크포인트 저장 흐름; 실제 임베딩·GPT 지연·판정 품질 제외",
    }
    output = root / "output/validation/realistic-manuscript-20260912/long-episodes.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
