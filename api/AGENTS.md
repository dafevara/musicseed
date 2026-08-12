# musicseed-api — Agent Guide

`api/` is the REST API and orchestration surface for MusicSeed. It provides **JSON endpoints**
for every MusicSeed operation plus a **`handlers/`** layer of surface-agnostic orchestration
functions that both the CLI and web surfaces import directly. It is a **thin wrapper**: handlers
orchestrate calls to `musicseed-core`'s `services/` layer — they never touch the database, Plex,
or recommendation engine directly. If you find yourself adding business logic to a handler, it
belongs in `core/services/`.

Read the root `AGENTS.md` for product context and repo-wide safety rules, and `core/AGENTS.md`
for the logic this app calls. This file covers the API app only.

## Identity

- Distribution name: `musicseed-api`. Import package: `musicseed_api`.
- Stack: **FastAPI** (JSON-only — no templates, no static files, no HTML). The `handlers/` layer
  underneath is framework-free and importable by any surface.
- Depends on `musicseed-core` via an **editable path source** in `pyproject.toml`
  (`musicseed-core = { path = "../core", editable = true }`). No dependency on `musicseed-web`
  or `musicseed-cli` — the web surface consumes this API over HTTP.
- Own `pyproject.toml` + `uv.lock` + `.venv`. Run `uv` commands from inside `api/`.
- Started standalone via `uv run uvicorn musicseed_api.app:app` (port 8000) or the
  `musicseed-api` script entry point (port 8789). The Next.js web surface is a separate
  process that proxies `/api/*` to this server in development (see `web/AGENTS.md`).

## Architecture: the `handlers/` seam

`handlers/` is the **surface-agnostic orchestration layer** — the public API of this package,
and the primary layer other surfaces should call. It follows the same pattern as core's
`services/` layer, one level up: services do one thing; handlers orchestrate several services
into a user-facing operation. Each handler function:

- accepts plain kwargs (no HTTP request objects, no FastAPI imports),
- calls one or more `musicseed.services` functions,
- handles config manipulation, job lifecycle, and error mapping,
- returns a **Pydantic result model** or a plain dict, and
- **never imports FastAPI, Starlette, or any HTTP framework**.

The JSON routes in `routes/` are thin wrappers that parse HTTP, call a handler, and return
JSON. Handlers are the reusable part — routes are the HTTP-specific projection.

## Handlers → core service (all logic is in core)

| Handler | Orchestrates |
|---|---|
| `handlers/discovery.run_discovery` | `services.discovery.discover` (with key filtering) |
| `handlers/discovery.run_plex_discovery` | `services.plex_discovery.discover_plex_servers` |
| `handlers/discovery.save_config_overrides` | `config.get_config` → `save_config` → `db.session.reset_engine` (persist only — no DB init) |
| `handlers/discovery.apply_config_and_init_db` | `save_config_overrides` → `services.library.initialize_database` |
| `handlers/library.get_library_status` | `services.library.get_status` |
| `handlers/library.run_import_job` | `services.jobs.update_progress` → `services.library.import_library` |
| `handlers/enrichment.save_spotify_creds` | `config.get_config` / `set_config` |
| `handlers/enrichment.run_enrich_job` | `services.jobs.update_progress` → `services.enrichment.enrich_tracks` |
| `handlers/dashboard.get_dashboard_snapshot` | `services.dashboard.get_dashboard` |
| `handlers/recommend.parse_seed_ids` | (pure utility — no service calls) |
| `handlers/recommend.typeahead_search` | `db.session.get_session` → query `Track` + `Artist` |
| `handlers/recommend.run_recommendations` | `services.recommend.get_recommendations` |
| `handlers/sonic.get_sonic_coverage` | `services.plex_analysis.get_sonic_status` |
| `handlers/sonic.trigger_sonic_refresh` | `services.plex_analysis.refresh_sonic_analysis` |
| `handlers/jobs.submit_job` | `services.jobs.get_manager` → `JobManager.submit` |
| `handlers/jobs.get_job_progress` | `services.jobs.get_job` |
| `handlers/jobs.cancel_job` | `services.jobs.get_manager` → `JobManager.request_cancel` |
| `handlers/jobs.delete_job` | `services.jobs.get_job` → `services.jobs.delete_job` |

## Code Map

- `src/musicseed_api/app.py`: **app assembly only** — `create_app()` mounts the JSON route
  modules and registers the central exception handlers (the single error contract mapping
  typed core exceptions to HTTP status codes). The module-level `app = create_app()` is the
  ASGI entry point (`musicseed_api.app:app`); keep it importable.
- `src/musicseed_api/server.py`: **public server entry point** — `serve(host, port, on_started)`
  wraps uvicorn programmatically. `main()` is the `musicseed-api` script entry point (port 8789
  by default) for standalone development.
- `src/musicseed_api/handlers/`: **orchestration layer** — one module per domain. No HTTP
  framework imports anywhere. Every function is callable from any surface. Modules:
  `discovery.py`, `library.py`, `enrichment.py`, `dashboard.py`, `recommend.py`, `sonic.py`,
  `jobs.py`. Shared constants (`IMPORT_KIND`, `ENRICH_KIND`, `DB_BLOCKERS`, `DISCOVERY_KEYS`)
  live in the handler that owns them — import them directly rather than duplicating.
- `src/musicseed_api/routes/`: **JSON endpoints** — one module per domain, each with an
  `APIRouter` named `router` (no prefix). These are
  thin wrappers: parse HTTP (Form, Query, path params), call a handler, return JSON. Modules:
  `discovery.py`, `library.py`, `enrichment.py`, `recommend.py`, `sonic.py`, `dashboard.py`,
  `jobs.py`, `playlists.py`.

- **API contract**: the OpenAPI schema is auto-generated from the routes (FastAPI serves it at
  `/openapi.json`). It is the single source of truth for the JSON shapes — do not maintain a
  separate hand-written spec. `tests/test_openapi_contract.py` asserts the schema exposes every
  operation so a removed or renamed route fails the build.

## Particularities to respect

- **Handlers never import FastAPI.** Keep them framework-free. Routes handle HTTP concerns
  (Form parsing, Query params, status codes). If a handler starts accepting `Request` or
  returning `Response`, the boundary has been crossed.
- **Core result models embed live ORM objects** and are not JSON-serializable (see
  `core/AGENTS.md`). Handlers return the raw Pydantic models as-is. JSON routes must project
  `Track` objects into plain dicts/DTOs (see `routes/recommend.py` for the pattern). Projection
  happens only in routes — never in handlers.
- **`enrich_tracks` calls `asyncio.run()` internally.** All routes that trigger enrichment
  are synchronous for this reason. Never call `enrich_tracks` from an `async def` route; if
  you need async, offload to a thread (`fastapi.concurrency.run_in_threadpool`).
- **Config manipulation stays in handlers.** Surfaces (web, cli) should not call
  `get_config` / `set_config` / `reset_engine` directly. Handlers encapsulate config changes
  so credentials flow through one controlled path.
- **Job runnables** (`run_import_job`, `run_enrich_job`) accept `job_id` as the first
  positional arg (the `JobManager` convention). They call `update_progress` at checkpoints
  so the UI can render progress. They are synchronous, blocking functions — the manager
  runs them in daemon threads.
- **Route prefixes are applied by the consumer.** API routes have no URL prefix. The Next.js
  web dev server rewrites `/api/*` to this server (standalone on `:8789`). Do not add a prefix
  to route modules — the caller owns the mount point.
- **Secrets in routes.** Token and credential fields arrive via POST bodies (`Form`), are
  passed to handlers, and are never placed in JSON responses. The discovery route's
  `extract_overrides` helper separates secrets from sticky form values — secrets go to
  discovery, but only non-secret fields are echoed back.

## Dependencies

`fastapi`, `uvicorn`, `python-multipart`, `musicseed-core` (editable path); dev group:
`pytest`, `httpx`. After changing core, run `uv lock` in `api/` so its lockfile re-resolves
against the updated core. Surfaces that depend on api (`web/`) must also re-lock:
`cd ../web && uv lock`.

## Run / verify (from `api/`)

```bash
uv sync                                  # installs core editable + fastapi/uvicorn
uv run uvicorn musicseed_api.app:app --reload   # serve at http://127.0.0.1:8000
curl http://127.0.0.1:8000/discovery     # JSON discovery result (no /api prefix standalone)
uv run ruff check src tests
uv run pytest tests -q                   # offline suite — stubs Plex/DB, no real data
python3 -m compileall -q src/musicseed_api
```

The test suite (`tests/`) covers every route module and the framework-free handler
layer with `TestClient`. It stubs Plex and DB access at the handler/service boundary
(via `monkeypatch`), so it runs offline with no Plex server and no real database. The
`tests/conftest.py` fixture resets config and the DB engine between tests; anything that
touches the real database or Plex should still be exercised through core's own fixtures
(see `core/AGENTS.md`).
