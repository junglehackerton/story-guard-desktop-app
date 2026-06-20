#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export CARGO_HOME="$ROOT_DIR/.cargo"
export RUSTUP_HOME="$ROOT_DIR/.rustup"
export PATH="$CARGO_HOME/bin:$PATH"

npm run build
(cd src-tauri && cargo check)
