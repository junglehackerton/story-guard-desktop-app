"""Project review-window count for a realistic long-running web novel."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from backend.app.database import Database
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService

EPISODES = int(os.environ.get("STORYGUARD_BENCH_EPISODES", "100"))
CHARS_PER_EPISODE = int(os.environ.get("STORYGUARD_BENCH_CHARS_PER_EPISODE", "6200"))
BASE = (
    "유나는 새벽의 항구에서 봉인된 기록을 펼쳤다. "
    "도윤은 계약의 조건을 다시 확인했고, 경비대는 검은 종루의 문을 지켰다. "
)

with tempfile.TemporaryDirectory(prefix="storyguard-scale-") as directory:
    root_dir = Path(directory)
    repo = StoryRepository(Database(root_dir / "scale.sqlite"))
    project = repo.create_project("100회 장편 스케일 검증")
    splitter = RagService.__new__(RagService)
    for chapter in range(EPISODES):
        text = (BASE * ((CHARS_PER_EPISODE // len(BASE)) + 1))[:CHARS_PER_EPISODE]
        doc = repo.add_document(project.id, root_dir / f"{chapter + 1}.txt", f"{chapter + 1}화", "txt", str(chapter), text, chapter)
        chunks = splitter.split_text(text, doc.id, project.id)
        repo.replace_chunks(project.id, doc.id, [chunk.text for chunk in chunks])

    class RagStub:
        repository = repo

        def sync_project(self, project_id, progress=None):
            rows = repo.list_chunks(project_id)
            if progress:
                progress(len(rows), len(rows))
            return len(rows)

        def retrieve(self, *args, **kwargs):
            return []

    calls = 0

    def complete(model, prompt, **kwargs):
        nonlocal_calls[0] += 1
        return {"text": '{"entities": [], "relations": [], "issues": []}'}

    # Keep the counter mutable without relying on module globals.
    nonlocal_calls = [0]
    started = time.monotonic()
    result = GptStoryAnalyzer(repo, RagStub(), SimpleNamespace(complete=complete)).analyze(
        project.id, "GPT-6.5-Luna", "medium"
    )
    elapsed = time.monotonic() - started
    job = repo.latest_analysis_job(project.id)
    report = {
        "episodes": EPISODES,
        "chars": EPISODES * CHARS_PER_EPISODE,
        "chunks": len(repo.list_chunks(project.id)),
        "review_windows": len(job.window_details),
        "provider_calls": nonlocal_calls[0],
        "failed_windows": result["failed_window_count"],
        "status": job.status.value,
        "orchestration_seconds": round(elapsed, 3),
        "serial_provider_projection": {
            "at_15s_per_window_minutes": round(nonlocal_calls[0] * 15 / 60, 1),
            "at_30s_per_window_minutes": round(nonlocal_calls[0] * 30 / 60, 1),
            "at_60s_per_window_minutes": round(nonlocal_calls[0] * 60 / 60, 1),
            "note": "실제 GPT 응답 지연을 측정한 값이 아니라, 순차 요청일 때의 사용자 대기 상한 감을 보여주는 단순 환산",
        },
        "scope": "동일 청킹·검토 구간 생성과 저장 흐름만 검증; 로컬 임베딩·실제 GPT 지연·품질 제외",
    }
    output = root / "output/validation/realistic-manuscript-20260912" / f"scale-{EPISODES}-episodes.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
