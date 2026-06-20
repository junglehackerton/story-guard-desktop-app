#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/pyinstaller" ]]; then
  echo "PyInstaller is not installed. Run: . .venv/bin/activate && pip install -r backend/requirements.txt" >&2
  exit 1
fi

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) TARGET_TRIPLE="aarch64-apple-darwin" ;;
  Darwin-x86_64) TARGET_TRIPLE="x86_64-apple-darwin" ;;
  Linux-x86_64) TARGET_TRIPLE="x86_64-unknown-linux-gnu" ;;
  Linux-aarch64|Linux-arm64) TARGET_TRIPLE="aarch64-unknown-linux-gnu" ;;
  MINGW*-x86_64|MSYS*-x86_64|CYGWIN*-x86_64) TARGET_TRIPLE="x86_64-pc-windows-msvc" ;;
  *) echo "Unsupported sidecar target: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

mkdir -p src-tauri/binaries

.venv/bin/pyinstaller \
  --clean \
  --onefile \
  --name "story-guard-backend-${TARGET_TRIPLE}" \
  --distpath src-tauri/binaries \
  --workpath build/pyinstaller \
  --specpath build/pyinstaller \
  backend/sidecar.py

chmod +x "src-tauri/binaries/story-guard-backend-${TARGET_TRIPLE}" 2>/dev/null || true
echo "Built src-tauri/binaries/story-guard-backend-${TARGET_TRIPLE}"
