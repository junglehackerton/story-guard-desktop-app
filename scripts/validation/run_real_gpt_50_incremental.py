"""Extend the isolated real GPT run from 20 to 50 episodes.

The first twenty checkpoints are intentionally retained. The output verifies
that incremental analysis requests only the thirty new windows.
"""
from __future__ import annotations
import hashlib, json, os, resource, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DATA = Path(os.environ.get("STORY_GUARD_LOAD_DIR", "/tmp/storyguard-real-gpt-load"))
os.environ["STORY_GUARD_DATA_DIR"] = str(DATA)
from backend.app.database import Database
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.chatgpt import ChatGptConnection
from backend.app.services.rag import RagService
from backend.app.services.parser import split_chunks

def main() -> int:
    repo = StoryRepository(Database(DATA / "story_guard.sqlite"))
    project = repo.list_projects()[0]
    source = ROOT / "output/validation/goal-1-8-20260913/actual-50-episodes"
    existing = {d.chapter_index for d in repo.list_documents(project.id)}
    for index, path in enumerate(sorted(source.glob("episode-*.txt"), key=lambda p: int(p.stem.split("-")[-1]))):
        if index in existing: continue
        text = path.read_text(encoding="utf-8")
        doc = repo.add_document(project.id, path, f"episode-{index + 1:02d}", "txt",
                                hashlib.sha256(text.encode()).hexdigest(), text, index,
                                preserve_analysis=True)
        repo.replace_chunks(project.id, doc.id, split_chunks(text))
    connection = ChatGptConnection(Path.home() / "Library/Application Support/app.storyguard.desktop")
    started = time.monotonic(); before = resource.getrusage(resource.RUSAGE_SELF)
    try:
        status = connection.status()
        result = GptStoryAnalyzer(repo, RagService(DATA / "chroma", repository=repo), connection).analyze(
            project.id, os.environ.get("STORY_GUARD_LOAD_MODEL", "gpt-5.6-luna"),
            os.environ.get("STORY_GUARD_LOAD_EFFORT", "medium"), force=False)
        error = None
    except Exception as exc: result, error, status = None, str(exc), locals().get("status")
    finally: connection.transport.close()
    job = repo.latest_analysis_job(project.id)
    details = [d.model_dump() if hasattr(d, "model_dump") else d for d in (job.window_details if job else [])]
    after = resource.getrusage(resource.RUSAGE_SELF)
    payload = {"project_id": project.id, "episodes": len(repo.list_documents(project.id)),
               "chunks": len(repo.list_chunks(project.id)), "status": job.status.value if job else None,
               "elapsed_seconds": round(time.monotonic() - started, 2),
               "user_cpu_seconds": round(after.ru_utime - before.ru_utime, 2),
               "system_cpu_seconds": round(after.ru_stime - before.ru_stime, 2),
               "result": result, "error": error,
               "reused_windows": sum(bool(d.get("reused")) for d in details),
               "new_or_retried_windows": sum(not bool(d.get("reused")) for d in details),
               "failed_windows": [d for d in details if d.get("status") == "failed"],
               "scope": "20편 완료 체크포인트를 유지한 채 50편으로 확장한 실제 GPT 증분 분석."}
    (DATA / "real-gpt-50-incremental.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2)); return 0 if error is None else 1
if __name__ == "__main__": raise SystemExit(main())
