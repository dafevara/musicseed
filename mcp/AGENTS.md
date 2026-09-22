# musicseed-mcp — Agent Guide

`mcp/` is the **MCP server surface** for MusicSeed: it exposes playlist
creation and population as typed agent tools. It is a **thin adapter**: each
tool parses its arguments, offloads one synchronous `musicseed-core` service
call to a worker thread, and returns JSON. No recommendation, database, or
Plex logic lives here — that belongs in `core/services/`.

Read the root `AGENTS.md` for product context and repo-wide safety rules, and
`core/AGENTS.md` for the services this app calls.

## Identity

- Distribution name: `musicseed-mcp`. Import package: `musicseed_mcp`.
- Installed command: **`musicseed-mcp`** → `musicseed_mcp.server:main`
  (stdio transport).
- Depends on `musicseed-core` via an **editable path source** in
  `pyproject.toml`, like `cli/` and `api/`. It does **not** depend on the
  FastAPI `api/` app — no HTTP stack in this venv.
- Own `pyproject.toml` + `uv.lock` + `.venv`. Run `uv`/`musicseed-mcp` from
  inside `mcp/`.

## Code Map

- `src/musicseed_mcp/server.py`: the `MCPServer` instance (mcp 2.x renamed
  `FastMCP`), the `@mcp.tool()` async wrappers (each does
  `to_thread.run_sync(...)` over a `tools` function), and `main()`. `main()`
  parses `--transport stdio|sse|streamable-http`, `--host`, and `--port`;
  stdio is the default, the HTTP transports power `scripts/dev.sh` (8790) and
  URL-connecting hosts. Keep tool docstrings accurate — they become the
  agent-visible tool descriptions.
- `src/musicseed_mcp/tools.py`: **synchronous** tool implementations. Each
  calls one `musicseed.services` function and returns JSON-safe data (usually
  `.model_dump(mode="json")`). No async, no `FastMCP` imports here — this is
  the unit-testable seam.

## Particularities to respect

- **Thread offload.** Core services are synchronous (SQLAlchemy + httpx). Every
  tool runs its `tools` call through `anyio.to_thread.run_sync` so the MCP
  event loop is never blocked. Never call `services.enrichment.enrich_tracks`
  from the event loop (it calls `asyncio.run()` internally).
- **Preview/apply split is the safety model.** Preview tools never write to
  Plex. Write tools (`create_playlist`, `populate_playlist`) accept only
  previously-approved local track IDs; core validates the full selection before
  any write and rejects stale/missing IDs rather than writing a subset. Do not
  add a tool that generates-and-writes in one step.
- **Writes are idempotent.** Core reconciles against Plex's current playlist
  contents: `populate_playlist` reports `added_count` and
  `already_present_count`; `create_playlist` returns the existing playlist on
  an exact retry and raises a conflict on a name collision with different
  contents. Preserve these semantics.
- **Errors propagate.** Let core's `NotFoundError` / `ConfigurationError` /
  `PlexAPIError` surface as tool errors; do not swallow them into generic
  strings.
- **Weights via presets only.** Tools take a `preset` name resolved through
  `RECOMMENDATION_PRESETS`; do not expose six raw weight floats.

## Dependencies

`mcp`, `anyio`, `musicseed-core` (editable path); dev group: `ruff`, `pytest`.
After changing core, run `uv lock` in `mcp/` so its lockfile re-resolves
against the updated app.

## Run / verify (from `mcp/`)

```bash
uv sync
uv run ruff check src tests
uv run pytest tests -q            # offline; no DB/Plex required
uv run musicseed-mcp              # stdio server (JSON-RPC over stdin/stdout)
```

Tool behavior against real services is covered by `core/tests`; `mcp/tests`
asserts registration, preset mapping, and adapter shape only.
