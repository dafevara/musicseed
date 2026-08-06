# musicseed-web — Agent Guide

`web/` is the local web surface for MusicSeed: a **server-rendered** FastAPI app using Jinja
templates and HTMX for incremental updates. Like the CLI, it is a **thin wrapper**: routes parse
requests, call `musicseed-core`'s `services/` layer, and render results. No recommendation,
database, or Plex logic lives here — if you find yourself adding business logic to a route, it
belongs in `core`.

Read the root `AGENTS.md` for product context and repo-wide safety rules, and `core/AGENTS.md` for
the logic this app calls. This file covers the web app only.

## Identity

- Distribution name: `musicseed-web`. Import package: `musicseed_web`.
- Stack: **FastAPI + Jinja2 + HTMX**. No Node build step, no frontend framework, no server
  database, no queue, no containers. Keep it that way.
- Depends on `musicseed-core` via an **editable path source** in `pyproject.toml`
  (`musicseed-core = { path = "../core", editable = true }`).
- Own `pyproject.toml` + `uv.lock` + `.venv`. Run `uv` commands from inside `web/`.
- Started via the CLI: **`musicseed web`** (in `cli/`) runs `musicseed_web.server.serve` on
  `127.0.0.1:8788` by default and opens the browser once the server reports ready
  (`--no-open` skips the browser). Direct uvicorn (`uv run uvicorn musicseed_web.app:app`)
  still works for development.

## Code Map

- `src/musicseed_web/app.py`: **app assembly + routes** — `create_app()` builds the FastAPI app,
  mounts `/static`, and defines routes. The module-level `app = create_app()` is the ASGI entry
  point (`musicseed_web.app:app`); keep it importable.
- `src/musicseed_web/server.py`: **public server entry point** — `serve(host, port, on_started)`
  wraps uvicorn programmatically and fires `on_started` once the server accepts requests
  (the CLI uses it to time the browser launch). Surfaces start the app through this function,
  not by assembling uvicorn themselves.
- `src/musicseed_web/templates/`: Jinja templates. `base.html` is the page shell (loads CSS +
  vendored HTMX), `index.html` the root page, and `_*.html` are **HTMX partials** (fragments
  returned without the page shell — test them by asserting `"<html" not in response.text`).
- `src/musicseed_web/static/`: static assets mounted at `/static`.
  `static/js/htmx.min.js` is **vendored** (htmx.org 2.0.4) — no CDN dependency; update it by
  replacing the file, not by linking to a CDN.
- `tests/test_app.py`: smoke tests using `fastapi.testclient.TestClient` (root page renders,
  `/healthz` returns ok, the clock fragment returns a partial, static assets are served).

## Particularities to respect

- **Thin surface only.** Routes call `musicseed.services` and render. Never import from
  `musicseed_cli`, and never add Typer/Rich console output here.
- **Core result models embed live ORM objects** and are not JSON-serializable (see
  `core/AGENTS.md`). For HTML this is fine (Jinja reads attributes); if you ever add a JSON route,
  project results into plain dicts/DTOs first.
- **`services.enrichment.enrich_tracks` calls `asyncio.run()` internally** — never call it from an
  async route; offload to a thread (`fastapi.concurrency.run_in_threadpool`) if needed.
- **HTMX partials re-declare their own `hx-trigger`/`hx-swap`** (see `_clock.html`) so swapped-in
  content keeps updating. Follow that pattern for self-refreshing fragments.
- Keep JavaScript minimal. Prefer HTMX attributes over custom scripts.

## Dependencies

`fastapi`, `uvicorn`, `jinja2`, `musicseed-core` (editable path); dev group: `pytest`, `httpx`
(for `TestClient`). After changing core, run `uv lock` in `web/` so its lockfile re-resolves
against the updated core.

## Run / verify (from `web/`)

```bash
uv sync                                  # installs core editable + fastapi/uvicorn/jinja2
uv run uvicorn musicseed_web.app:app --reload   # serve at http://127.0.0.1:8000
curl http://127.0.0.1:8000/healthz       # {"status":"ok","service":"musicseed-web"}
uv run pytest tests -q                   # smoke tests (no Plex/DB required)
uv run ruff check src tests
python3 -m compileall -q src/musicseed_web
```

The scaffold routes touch no database, Plex, or network APIs, so tests are fully offline and safe.
When later issues add setup/import/dashboard routes, guard Plex writes behind explicit user
confirmation and follow the repo-wide safety rules (no full-library jobs without user intent).
