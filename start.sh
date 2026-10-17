#!/usr/bin/env bash
# One-command start for Linux, macOS and WSL:   ./start.sh
# Installs uv if needed (it brings Python and every dependency), then starts the app and opens it.
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "[coach] Installing uv (one-time setup)..."
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "[coach] Need curl or wget to install uv. On Ubuntu/WSL run: sudo apt install curl" >&2
    exit 1
  fi
fi

echo "[coach] Getting everything ready (the first run downloads Python and libraries, a few minutes)..."
exec uv run --extra engine python launch.py "$@"
