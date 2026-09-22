#!/usr/bin/env bash
# Start the MusicSeed API (8789), the Next.js web UI (3000), and the MCP
# server (8790, streamable-http) together. One command for local development;
# Ctrl-C stops all processes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${API_PORT:-8789}"
WEB_PORT="${WEB_PORT:-3000}"
MCP_PORT="${MCP_PORT:-8790}"
API_URL="${API_URL:-http://127.0.0.1:8789}"
export MUSICSEED_LOG_LEVEL="${MUSICSEED_LOG_LEVEL:-DEBUG}"

API_PID=""
WEB_PID=""
MCP_PID=""

cleanup() {
  trap - INT TERM EXIT
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "$WEB_PID" ]] && kill "$WEB_PID" 2>/dev/null || true
  [[ -n "$MCP_PID" ]] && kill "$MCP_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "[dev] starting musicseed on 127.0.0.1:${API_PORT} ..."
(cd "$ROOT/api" && exec uv run musicseed --no-ui --host 127.0.0.1 --port "$API_PORT") &
API_PID=$!

echo "[dev] starting Next.js web UI on 127.0.0.1:${WEB_PORT} (proxying /api -> ${API_URL}) ..."
(cd "$ROOT/web" && API_URL="$API_URL" exec npm run dev -- --port "$WEB_PORT") &
WEB_PID=$!

echo "[dev] starting MCP server on 127.0.0.1:${MCP_PORT} (streamable-http) ..."
(cd "$ROOT/mcp" && exec uv run musicseed-mcp --transport streamable-http --host 127.0.0.1 --port "$MCP_PORT") &
MCP_PID=$!

wait
