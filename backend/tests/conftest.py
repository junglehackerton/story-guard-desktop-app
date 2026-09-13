"""Test bootstrap for running the backend suite from the repository root.

The application creates its SQLite/Chroma stores at import time.  Pointing the
test process at an isolated temporary directory keeps a plain ``pytest`` run
deterministic and prevents a developer's real Story Guard data from being
modified.
"""

import os
import tempfile

os.environ.setdefault("STORY_GUARD_DATA_DIR", tempfile.mkdtemp(prefix="story-guard-tests-"))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "False")
