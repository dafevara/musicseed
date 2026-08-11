# musicseed-api — Agent Guide

`api/` is the REST API surface for MusicSeed. It provides **JSON endpoints** for every
MusicSeed operation plus a **`handlers/`** layer of surface-agnostic orchestration functions
that the CLI and web surfaces can import directly. Like the CLI and web, this is a **thin
wrapper**: handlers orchestrate calls to `musicseed-core`'s `services/` layer; they never
touch the database, Plex, or recommendation engine directly.

Read the root `AGENTS.md` for product context and repo-wide safety rules, and `core/AGENTS.md`
for the logic this app calls. This file covers the API app only.

## Identity

- Distribution name: `musicseed-api`. Import package: `musicseed_api`.
- Stack: **FastAPI** (JSON-only — no templates, no static files, no HTML).
- Depends on `musicseed-core` via an **editable path source** in `pyproject.toml`
  (`musicseed-core = { path = "../core", editable = true }`).
- Own `pyproject.toml` + `uv.lock` + `.venv`. Run `uv` commands from inside `api/`.
- Started standalone via `uv run uvicorn musicseed_api.app:app` or the
  `musicseed-api` script entry point. The web surface can mount the API routers
  in-process.

## Architecture: the `handlers/` seam

`handlers/` is the **surface-agnostic orchestration layer** — the public API of this package,
and the layer other surfaces (web, cli) should call. Each handler function:

- accepts plain kwargs,
- calls one or more `musicseed.services` functions,
- handles config manipulation and error mapping,
- returns a **Pydantic result model** or a plain dict, and
- **never imports FastAPI, Starlette, or any HTTP framework**.

This is the same pattern as core's `services/` layer, one level up: services do one thing;
handlers orchestrate several services into a user-facing operation.

Handler modules:

- `handlers/discovery.py`: `run_discovery`, `wizard_ready`, `extract_overrides`,
  `apply_config_and_init_db`, plus shared constants `DB_BLOCKERS` / `DISCOVERY_KEYS`.
- `handlers/library.py`: `get_library_status`, `run_import_job`, `IMPORT_KIND`.
- `handlers/enrichment.py`: `save_spotify_creds`, `run_enrich_job`, `ENRICH_KIND`.
- `handlers/dashboard.py`: `get_dashboard_snapshot`.
- `handlers/recommend.py`: `parse_seed_ids`, `load_seed_tracks`, `typeahead_search`,
  `run_recommendations`.
- `handlers/sonic.py`: `get_sonic_coverage`, `trigger_sonic_refresh`.
- `handlers/jobs.py`: `submit_job`, `get_job_progress`, `cancel_job`.

## Code Map

- `src/musicseed_api/app.py`: **app assembly only** — `create_app()` mounts the JSON
  route modules. The module-level `app = create_app()` is the ASGI entry point
  (`musicseed_api.app:app`).
- `src/musicseed_api/server.py`: **public server entry point** — `serve(host, port, on_started)`
  wraps uvicorn programmatically (same pattern as `musicseed_web.server`). `main()` is the
  `musicseed-api` script entry point (port 8789 by default).
- `src/musicseed_api/handlers/`: **orchestration layer** — no HTTP imports. Callable from
  any surface. The web surface imports these directly; the CLI surface can too.
- `src/musicseed_api/routes/`: **JSON endpoints** — one module per domain, each an
  `APIRouter` named `router`, prefixed with `/api`. These are thin wrappers: parse HTTP,
  call a handler, return JSON. Available route groups: `discovery`, `library`,
  `enrichment`, `recommend`, `sonic`, `dashboard`, `jobs`.

## Particularities to respect

- **Handlers never import FastAPI.** Keep them framework-free. Routes handle HTTP concerns.
- **Core result models embed ORM objects** and are not JSON-serializable. JSON routes must
  project into dicts/DTOs (see `routes/recommend.py` for the pattern). Handlers return the
  raw Pydantic models; projection happens only in routes.
- **`enrich_tracks` calls `asyncio.run()` internally.** Never call it from an async route;
  the enrichment routes are sync for this reason.
- **Config manipulation stays in handlers.** Surfaces should not call `get_config` /
  `set_config` / `reset_engine` directly — handlers encapsulate that.
- **Job runnables** (`run_import_job`, `run_enrich_job`) accept `job_id` as the first
  positional arg (the `JobManager` convention) and call `update_progress` at checkpoints.

## Dependencies

`fastapi`, `uvicorn`, `musicseed-core` (editable path); dev group: `pytest`, `httpx`.
After changing core, run `uv lock` in `api/` so its lockfile re-resolves against the
updated core.

## Run / verify (from `api/`)

```bash
uv sync
uv run uvicorn musicseed_api.app:app --reload   # serve at http://127.0.0.1:8000
curl http://127.0.0.1:8000/api/discovery
uv run ruff check src
python3 -m compileall -q src/musicseed_api
```
