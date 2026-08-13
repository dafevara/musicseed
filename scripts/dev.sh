#!/usr/bin/env bash
# Start the MusicSeed API (8789) and the Next.js web UI (3000) together.
# One command for local development; Ctrl-C stops both processes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${API_PORT:-8789}"
WEB_PORT="${WEB_PORT:-3000}"
API_URL="${API_URL:-http://127.0.0.1:8789}"

API_PID=""
WEB_PID=""

cleanup() {
  trap - INT TERM EXIT
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "$WEB_PID" ]] && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "[dev] starting musicseed on 127.0.0.1:${API_PORT} ..."
(cd "$ROOT/api" && exec uv run musicseed --no-ui --host 127.0.0.1 --port "$API_PORT") &
API_PID=$!

echo "[dev] starting Next.js web UI on 127.0.0.1:${WEB_PORT} (proxying /api -> ${API_URL}) ..."
(cd "$ROOT/web" && API_URL="$API_URL" exec npm run dev -- --port "$WEB_PORT") &
WEB_PID=$!

wait
