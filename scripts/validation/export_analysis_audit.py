"""Export and verify the evidence envelope used by a GPT analysis run.

This is intentionally read-only. It makes the parity question explicit:
every chunk ID recorded immediately before a provider call must still resolve
to the same canonical SQLite text when the run is exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
from pathlib import Path

from backend.app.database import Database
from backend.app.repository import StoryRepository


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_audit(repo: StoryRepository, project_id: int) -> dict:
    job = repo.latest_analysis_job(project_id)
    if job is None:
        raise ValueError(f"project {project_id} has no analysis job")
    chunks = {int(row["id"]): row for row in repo.list_chunks(project_id)}
    windows = []
    for detail in job.window_details:
        context_ids = [int(value) for value in detail.get("context_chunk_ids", [])]
        missing = [value for value in context_ids if value not in chunks]
        context = [
            {
                "chunk_id": value,
                "document_id": int(chunks[value]["document_id"]),
                "chunk_index": int(chunks[value]["chunk_index"]),
                "text": str(chunks[value]["text"]),
                "text_sha256": _sha256(str(chunks[value]["text"])),
            }
            for value in context_ids
            if value in chunks
        ]
        envelope = json.dumps(
            [(item["chunk_id"], item["text"]) for item in context],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        windows.append({
            "index": detail.get("index"),
            "status": detail.get("status"),
            "stage": detail.get("stage"),
            "elapsed_seconds": float(detail.get("elapsed_seconds", 0) or 0),
            "attempts": int(detail.get("attempts", 0) or 0),
            "reused": bool(detail.get("reused", False)),
            "prompt_hash": detail.get("prompt_hash"),
            "prompt_hash_recorded": bool(detail.get("prompt_hash")),
            "owned_chunk_ids": detail.get("owned_chunk_ids", []),
            "retrieved_chunk_ids": detail.get("retrieved_chunk_ids", []),
            "context_chunk_ids": context_ids,
            "context_envelope_sha256": _sha256(envelope),
            "recorded_context_envelope_sha256": detail.get("context_envelope_sha256"),
            "context": context,
            "missing_context_chunk_ids": missing,
            "parity_ok": not missing and (
                not detail.get("context_envelope_sha256")
                or detail.get("context_envelope_sha256") == _sha256(envelope)
            ),
        })
    elapsed = [window["elapsed_seconds"] for window in windows if window["elapsed_seconds"] > 0]
    requests = sum(window["attempts"] for window in windows if not window["reused"])
    return {
        "project_id": project_id,
        "job_id": job.id,
        "status": job.status.value,
        "review_context": job.review_context,
        "windows": windows,
        "timing_summary": {
            "measured_window_count": len(elapsed),
            "total_window_seconds": round(sum(elapsed), 3),
            "median_window_seconds": round(statistics.median(elapsed), 3) if elapsed else 0,
            "max_window_seconds": round(max(elapsed), 3) if elapsed else 0,
            "provider_attempts_from_checkpoints": requests,
        },
        "issues": [issue.model_dump() for issue in repo.open_issues(project_id)],
        "parity_ok": all(window["parity_ok"] for window in windows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(os.environ.get("STORY_GUARD_DATA_DIR", Path.home() / ".story-guard"))
    audit = build_audit(StoryRepository(Database(root / "story_guard.sqlite")), args.project_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "job_id": audit["job_id"], "parity_ok": audit["parity_ok"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
