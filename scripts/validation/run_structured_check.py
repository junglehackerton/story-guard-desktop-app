#!/usr/bin/env python3
"""Run an expensive validation script and preserve an actionable JSON result.

The model checks intentionally use the repository's real runtime. This wrapper
does not turn runtime failures into passes; it records the failed stage so a
missing model, device allocation error, and a genuine retrieval score are not
confused with one another.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def stage_for(script: Path) -> str:
    name = script.name
    if name in {"validate_hybrid.py", "lifecycle.py"}:
        return "embedding_runtime"
    if name == "validate_gemma_app.py":
        return "gemma_runtime"
    return "validation_runtime"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("script", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    script = args.script.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(script)]
    started = datetime.now(timezone.utc)
    completed = subprocess.run(command, cwd=script.parents[2], text=True, capture_output=True)
    report = {
        "status": "passed" if completed.returncode == 0 else "failed",
        "stage": None if completed.returncode == 0 else stage_for(script),
        "script": str(script),
        "command": command,
        "started_at": started.isoformat(),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-6000:],
        "stderr_tail": completed.stderr[-6000:],
        "environment": {
            "story_guard_embed_n_ctx": os.getenv("STORY_GUARD_EMBED_N_CTX"),
            "story_guard_data_dir": os.getenv("STORY_GUARD_DATA_DIR"),
        },
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "stage", "returncode", "script")}, ensure_ascii=False))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
