"""Resume a persisted long-manuscript GPT run and emit reproducible metrics.

This intentionally opens an existing validation SQLite/Chroma pair. It does
not create a new manuscript or delete checkpoints, so a provider outage can be
retried later without losing completed windows.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import Database
from backend.app.pipeline.gpt_analyzer import GptStoryAnalyzer
from backend.app.repository import StoryRepository
from backend.app.services.chatgpt import ChatGptConnection
from backend.app.services.rag import RagService


def serialize_windows(job):
    return [detail.model_dump() if hasattr(detail, "model_dump") else detail
            for detail in (job.window_details if job else [])]


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume a Story Guard long GPT run")
    parser.add_argument("--root", type=Path, required=True,
                        help="directory containing story.sqlite and chroma/")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--effort", default="low")
    parser.add_argument("--batch-limit", type=int, default=20)
    parser.add_argument("--auth-root", type=Path,
                        default=Path.home() / "Library/Application Support/app.storyguard.desktop",
                        help="Story Guard app data directory containing chatgpt-auth/")
    parser.add_argument("--output", type=Path,
                        help="optional JSON output path")
    parser.add_argument("--dry-run", action="store_true",
                        help="report persisted window status without contacting GPT")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    repo = StoryRepository(Database(root / "story.sqlite"))
    if args.dry_run:
        job = repo.latest_analysis_job(args.project_id)
        payload = {
            "root": str(root), "project_id": args.project_id,
            "dry_run": True,
            "job_status": job.status.value if job else None,
            "job_message": job.message if job else None,
            "window_details": serialize_windows(job),
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        print(encoded)
        if args.output:
            args.output.expanduser().resolve().write_text(encoded + "\n", encoding="utf-8")
        return 0
    rag = RagService(root / "chroma", repository=repo)
    connection = ChatGptConnection(args.auth_root.expanduser().resolve())
    started = time.monotonic()
    try:
        status = connection.status()
        result = GptStoryAnalyzer(repo, rag, connection).analyze(
            args.project_id,
            args.model,
            args.effort,
            force=False,
            batch_limit=args.batch_limit,
        )
        error = None
    except Exception as exc:  # preserve diagnostics for a later retry
        result = None
        error = str(exc)
        status = status if "status" in locals() else None
    finally:
        connection.transport.close()

    job = repo.latest_analysis_job(args.project_id)
    payload = {
        "root": str(root),
        "project_id": args.project_id,
        "model": args.model,
        "effort": args.effort,
        "batch_limit": args.batch_limit,
        "account_status": status,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "result": result,
        "error": error,
        "job_status": job.status.value if job else None,
        "job_message": job.message if job else None,
        "window_details": serialize_windows(job),
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.expanduser().resolve().write_text(encoded + "\n", encoding="utf-8")
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
