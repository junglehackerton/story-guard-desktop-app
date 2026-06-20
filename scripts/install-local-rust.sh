#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export CARGO_HOME="$ROOT_DIR/.cargo"
export RUSTUP_HOME="$ROOT_DIR/.rustup"

if [[ -x "$CARGO_HOME/bin/cargo" ]]; then
  "$CARGO_HOME/bin/cargo" --version
  exit 0
fi

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
  | sh -s -- -y --profile minimal --default-toolchain stable

"$CARGO_HOME/bin/rustc" --version
"$CARGO_HOME/bin/cargo" --version
