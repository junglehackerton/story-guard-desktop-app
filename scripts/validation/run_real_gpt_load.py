"""Run a bounded real-provider load check against an isolated Story Guard project.

The script intentionally uses a fresh SQLite/Chroma directory and the user's
existing local ChatGPT device session. It records only timings, counts, and
window diagnostics; manuscript text and provider responses are never written.
"""
from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATA = Path(os.environ.get("STORY_GUARD_LOAD_DIR", "/tmp/storyguard-real-gpt-load"))
DATA.mkdir(parents=True, exist_ok=True)
MODEL_DIR = Path.home() / "Library/Application Support/app.storyguard.desktop/models"
(DATA / "models").mkdir(exist_ok=True)
for name in ("Qwen3-Embedding-0.6B-Q8_0.gguf", "qwen2.5-1.5b-instruct-q4_k_m.gguf"):
    link = DATA / "models" / name
    target = MODEL_DIR / name
    if target.exists() and not link.exists():
        link.symlink_to(target)
os.environ["STORY_GUARD_DATA_DIR"] = str(DATA)

from backend.app.database import Database
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.chatgpt import ChatGptConnection
from backend.app.services.rag import RagService
from backend.app.services.parser import split_chunks


def max_rss_mb() -> float:
    """Normalize ru_maxrss units (bytes on macOS, KiB on Linux)."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return value / divisor


def main() -> int:
    source_dir = ROOT / "output/validation/goal-1-8-20260913/actual-20-episodes"
    files = sorted(source_dir.glob("episode-*.txt"), key=lambda p: int(p.stem.split("-")[-1]))
    if len(files) < 20:
        raise RuntimeError(f"need 20 episodes, found {len(files)}")
    db = Database(DATA / "story_guard.sqlite")
    repo = StoryRepository(db)
    project = repo.create_project("실제 GPT 20편 부하 검증")
    for index, path in enumerate(files[:20]):
        text = path.read_text(encoding="utf-8")
        document = repo.add_document(project.id, path, f"episode-{index + 1:02d}", "txt",
                                     hashlib.sha256(text.encode()).hexdigest(), text, index)
        repo.replace_chunks(project.id, document.id, split_chunks(text))
    rag = RagService(DATA / "chroma", repository=repo)
    connection = ChatGptConnection(Path.home() / "Library/Application Support/app.storyguard.desktop")
    started = time.monotonic()
    before_rss = max_rss_mb()
    try:
        status = connection.status()
        if status.get("phase") != "connected":
            raise RuntimeError(f"ChatGPT session unavailable: {status}")
        result = GptStoryAnalyzer(repo, rag, connection).analyze(
            project.id, os.environ.get("STORY_GUARD_LOAD_MODEL", "gpt-5.6-luna"),
            os.environ.get("STORY_GUARD_LOAD_EFFORT", "medium"), force=False)
        error = None
    except Exception as exc:
        result, error = None, str(exc)
    finally:
        connection.transport.close()
    elapsed = round(time.monotonic() - started, 2)
    job = repo.latest_analysis_job(project.id)
    details = [d.model_dump() if hasattr(d, "model_dump") else d for d in (job.window_details if job else [])]
    payload = {
        "project_id": project.id, "episodes": 20,
        "chunks": len(repo.list_chunks(project.id)),
        "status": job.status.value if job else None,
        "elapsed_seconds": elapsed,
        "max_rss_delta_mb": round(max(0, max_rss_mb() - before_rss), 1),
        "result": result, "error": error,
        "windows": [{k: d.get(k) for k in ("index", "status", "stage", "attempts", "elapsed_seconds", "error", "error_code", "reused")} for d in details],
        "scope": "20편 실제 ChatGPT 구간 분석. 로컬 인덱스·GPT 요청·실패 격리·재개를 포함한 단일 실행 측정.",
    }
    out = DATA / "real-gpt-20.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
