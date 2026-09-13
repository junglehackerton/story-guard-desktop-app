"""Validate long-manuscript windowing without spending provider quota."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))

from backend.app.database import Database
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.rag import RagService

source = root / "output/validation/realistic-manuscript-20260912/manuscripts.json"
manuscripts = json.loads(source.read_text())
out = root / "output/validation/realistic-manuscript-20260912"
repo = StoryRepository(Database(out / "orchestration.sqlite"))
project = repo.create_project("현실 분량 오케스트레이션 검증")
splitter = RagService.__new__(RagService)
chunk_texts = []
for chapter, text in sorted(manuscripts.items(), key=lambda item: int(item[0])):
    chapter_index = int(chapter) - 1
    doc = repo.add_document(project.id, out / f"{chapter}.txt", f"{chapter}화", "txt", chapter, text, chapter_index)
    chunks = splitter.split_text(text, doc.id, project.id)
    repo.replace_chunks(project.id, doc.id, [chunk.text for chunk in chunks])
    chunk_texts.extend(repo.list_chunks(project.id)[-len(chunks):])

class RagStub:
    repository = repo

    def sync_project(self, project_id, progress=None):
        rows = repo.list_chunks(project_id)
        if progress:
            progress(len(rows), len(rows))
        return len(rows)

    def retrieve(self, project_id, query, limit=4, strategy="hybrid"):
        rows = repo.list_chunks(project_id)
        return [{"chunk_id": row["id"], "text": row["text"]} for row in rows[:limit]]

calls = 0
def complete(model, prompt, **kwargs):
    global calls
    calls += 1
    return {"text": '{"entities": [], "relations": [], "issues": []}'}

start = time.monotonic()
result = GptStoryAnalyzer(repo, RagStub(), SimpleNamespace(complete=complete)).analyze(project.id, "GPT-6.5-Luna", "medium")
elapsed = time.monotonic() - start
job = repo.latest_analysis_job(project.id)
report = {
    "chapters": len(manuscripts),
    "total_chars": sum(len(text) for text in manuscripts.values()),
    "chunks": len(repo.list_chunks(project.id)),
    "review_windows": len(job.window_details),
    "provider_calls": calls,
    "failed_windows": result["failed_window_count"],
    "status": job.status.value,
    "orchestration_seconds": round(elapsed, 3),
    "scope": "GPT 응답을 정상 빈 JSON으로 대체한 분할·진행·저장 흐름 검증; 실제 모델 품질·제공자 지연 제외",
}

# A second pass injects one transient provider failure into the middle window.
# The follow-up run must reuse the 19 durable checkpoints and request only the
# isolated failed window.
calls = 0
fail_phase = True
def flaky_complete(model, prompt, **kwargs):
    global calls, fail_phase
    calls += 1
    if fail_phase and calls >= 11:
        # Fail all three bounded attempts for one window, then let subsequent
        # windows proceed so the run becomes partial instead of aborting.
        if calls >= 13:
            fail_phase = False
        raise RuntimeError("일시적 응답 시간 초과")
    return {"text": '{"entities": [], "relations": [], "issues": []}'}

flaky = GptStoryAnalyzer(repo, RagStub(), SimpleNamespace(complete=flaky_complete))
partial = flaky.analyze(project.id, "GPT-6.5-Luna", "medium", force=True)
partial_status = repo.latest_analysis_job(project.id).status.value
before_retry = calls
retried = flaky.analyze(project.id, "GPT-6.5-Luna", "medium", force=False)
report["failure_isolation"] = {
    "first_status": partial_status,
    "first_failed_windows": partial["failed_window_count"],
    "retry_status": repo.latest_analysis_job(project.id).status.value,
    "retry_provider_calls": calls - before_retry,
    "retry_failed_windows": retried["failed_window_count"],
}
(out / "orchestration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
