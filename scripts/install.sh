#!/usr/bin/env bash
# Install MusicSeed from a git clone: sync Python apps, build the static UI,
# put `musicseed` on PATH. Node is required here; runtime is Python only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing $1." >&2
    echo "$2" >&2
    exit 1
  fi
}

need python3 "Install Python 3.12+ from https://www.python.org/downloads/"
need uv "Install uv from https://docs.astral.sh/uv/getting-started/installation/"
need node "Install Node.js (with npm) from https://nodejs.org/"
need npm "Install Node.js (with npm) from https://nodejs.org/"

py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' || {
  echo "Python ${py_ver} is too old. MusicSeed needs 3.12+." >&2
  exit 1
}

echo "[install] syncing core ..."
(cd "$ROOT/core" && uv sync)

echo "[install] syncing api ..."
(cd "$ROOT/api" && uv sync)

echo "[install] building web UI ..."
(cd "$ROOT/web" && npm ci && npm run build)

echo "[install] installing musicseed onto PATH ..."
uv tool install --editable "$ROOT/api"

echo
echo "Done. Start MusicSeed with:"
echo "  musicseed"
echo "then open http://127.0.0.1:8789"
echo
echo "Optional CLI (no Node, no server):"
echo "  cd $ROOT/cli && uv sync"
echo "  uv run musicseed-cli --help"
