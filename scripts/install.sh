#!/usr/bin/env bash
# Install MusicSeed from a git clone or release archive: create a Python venv,
# install core + api into it, build the static UI, put `musicseed` on PATH.
# End users need only Python 3.12+ and Node.js — uv is a development-only tool.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
BIN_DIR="$HOME/.local/bin"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing $1." >&2
    echo "$2" >&2
    exit 1
  fi
}

need python3 "Install Python 3.12+ from https://www.python.org/downloads/"
need node "Install Node.js (with npm) from https://nodejs.org/"
need npm "Install Node.js (with npm) from https://nodejs.org/"

py_ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' || {
  echo "Python ${py_ver} is too old. MusicSeed needs 3.12+." >&2
  exit 1
}

echo "[install] creating virtualenv at $VENV ..."
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV" || {
    echo "Could not create a virtualenv." >&2
    echo "On Debian/Ubuntu, install venv support first: sudo apt install python3-venv" >&2
    exit 1
  }
else
  echo "[install] reusing existing virtualenv (delete $VENV to start fresh)"
fi

echo "[install] installing core + api + cli ..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$ROOT/core" -e "$ROOT/api" -e "$ROOT/cli"

echo "[install] building web UI ..."
(cd "$ROOT/web" && npm ci && npm run build)

echo "[install] linking musicseed + musicseed-cli onto PATH ..."
mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/musicseed" "$BIN_DIR/musicseed"
ln -sf "$VENV/bin/musicseed-cli" "$BIN_DIR/musicseed-cli"
if ! command -v musicseed >/dev/null 2>&1; then
  echo "Note: $BIN_DIR is not on your PATH. Add it, e.g.:" >&2
  echo "  export PATH=\"$BIN_DIR:\$PATH\"" >&2
fi

echo
echo "Done. Start MusicSeed with:"
echo "  musicseed"
echo "then open http://127.0.0.1:8789"
echo
echo "The CLI is also on PATH (no server, no Node):"
echo "  musicseed-cli --help"
