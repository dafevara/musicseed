#!/usr/bin/env bash
# Serve consistent snapshots of Plex's two SQLite databases over HTTP, so a
# MusicSeed install on another machine can import from this Plex host.
#
# Usage: scripts/serve-plex-db-snapshot.sh [PLEX_DATA_DIR] [PORT]
#
# Produces fresh snapshots (via sqlite3 VACUUM INTO, which yields a consistent
# single-file copy) into a temporary directory and serves them with Python's
# built-in HTTP server under the exact names MusicSeed expects:
#   com.plexapp.plugins.library.db
#   com.plexapp.plugins.library.blobs.db
#
# LAN only: the server is unauthenticated and serves only those two files —
# never Plex tokens or credentials.
set -euo pipefail

PLEX_DATA_DIR="${1:-}"
PORT="${2:-9000}"

if [[ -z "$PLEX_DATA_DIR" ]]; then
  for candidate in \
    "$HOME/Library/Application Support/Plex Media Server" \
    "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server" \
    "/var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server" \
    "$HOME/.local/share/plexmediaserver/Library/Application Support/Plex Media Server"; do
    if [[ -d "$candidate" ]]; then
      PLEX_DATA_DIR="$candidate"
      break
    fi
  done
fi

if [[ -z "$PLEX_DATA_DIR" || ! -d "$PLEX_DATA_DIR" ]]; then
  echo "Could not find the Plex data directory. Pass it as the first argument." >&2
  exit 1
fi

command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 CLI is required" >&2; exit 1; }

DB_DIR="$PLEX_DATA_DIR/Plug-in Support/Databases"
LIBRARY_DB="$DB_DIR/com.plexapp.plugins.library.db"
BLOBS_DB="$DB_DIR/com.plexapp.plugins.library.blobs.db"

SERVE_DIR="$(mktemp -d)"
trap 'rm -rf "$SERVE_DIR"' EXIT

echo "Snapshotting $LIBRARY_DB ..."
sqlite3 "$LIBRARY_DB" "VACUUM INTO '$SERVE_DIR/com.plexapp.plugins.library.db'"

if [[ -f "$BLOBS_DB" ]]; then
  echo "Snapshotting $BLOBS_DB ..."
  sqlite3 "$BLOBS_DB" "VACUUM INTO '$SERVE_DIR/com.plexapp.plugins.library.blobs.db'"
else
  echo "  (no blobs database found — sonic vectors won't be available)" >&2
fi

echo
echo "Serving snapshots on port $PORT"
echo "Point MusicSeed at:  http://<this-host's-LAN-IP>:$PORT"
echo
cd "$SERVE_DIR" && python3 -m http.server "$PORT"
