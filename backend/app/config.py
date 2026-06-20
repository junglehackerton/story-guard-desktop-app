from __future__ import annotations

import os
from pathlib import Path


def app_data_dir() -> Path:
    configured = os.getenv("STORY_GUARD_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".story-guard").resolve()


def database_path() -> Path:
    return app_data_dir() / "story_guard.sqlite"


def chroma_path() -> Path:
    return app_data_dir() / "chroma"


def models_path() -> Path:
    return app_data_dir() / "models"
