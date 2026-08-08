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

- `src/musicseed_web/app.py`: **app assembly only** — `create_app()` mounts `/static` and includes
  the route modules. The module-level `app = create_app()` is the ASGI entry point
  (`musicseed_web.app:app`); keep it importable.
- `src/musicseed_web/server.py`: **public server entry point** — `serve(host, port, on_started)`
  wraps uvicorn programmatically and fires `on_started` once the server accepts requests
  (the CLI uses it to time the browser launch). Surfaces start the app through this function,
  not by assembling uvicorn themselves.
- `src/musicseed_web/render.py`: shared `Jinja2Templates` instance + `BASE_DIR` (avoids circular
  imports between app assembly and route modules). Registers `nav.nav_context` as a template
  context processor, so every rendered template receives the navigation.
- `src/musicseed_web/nav.py`: the shell's section list (`SECTIONS`) and `active_section(path)`,
  which resolves the current section **from the request path, server-side** — there is no
  client-side router. Sections without a screen yet carry no `href` and render as inert labels
  rather than dead links. Add or activate a section here, not in `base.html`.
- `src/musicseed_web/routes/`: **one module per page/flow**, each with an `APIRouter` named
  `router`. `home.py`: `/` (redirects fresh installs to `/setup` when the MusicSeed DB doesn't
  exist), `/healthz`, `/fragments/clock`. `setup.py`: the first-run wizard — `GET /setup`
  (explainer shell), `GET /setup/results` (auto-discovery via HTMX on load), `POST /setup/check`
  (manual overrides → re-run discovery), `POST /setup/init-db` (creates the database using
  resolved values; safe on an existing database). Wizard routes only call core services
  (`discover`, `initialize_database`); they never touch the filesystem/Plex directly and never
  start import or enrichment.
- `src/musicseed_web/templates/`: Jinja templates. `base.html` is the page shell — header, the
  section navigation, and a CSS grid of `header / nav / main` (loads CSS + vendored HTMX);
  `index.html` the root page, `setup.html` the wizard shell, and `_*.html` are
  **HTMX partials** (fragments returned without the page shell — test them by asserting
  `"<html" not in response.text`). `_setup_results.html` renders the full discovery result:
  per-check badges + actionable guidance per `Reason` code, a review panel when ready, or the
  manual fix-and-retry form otherwise.
- `src/musicseed_web/static/`: static assets mounted at `/static`.
  `static/js/htmx.min.js` is **vendored** (htmx.org 2.0.4) — no CDN dependency; update it by
  replacing the file, not by linking to a CDN.
- `tests/`: `TestClient` smoke + wizard tests. `conftest.py` has `make_discovery(...)` factories
  so route tests never touch the real Plex installation, filesystem state, or network — patch
  `musicseed_web.routes.<module>.discover` with them.

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
- **Secrets discipline (wizard and beyond):** tokens arrive via POST bodies (`Form`), are
  rendered only as `••••••••`/“configured”, never placed in URLs or query strings, and never
  echoed back into form values. Form fields need `python-multipart` (a real dependency).
- **Setup wizard readiness ≠ `DiscoveryResult.ready`.** A missing MusicSeed DB is the normal
  fresh-install state, so `routes/setup.py::_wizard_ready` only blocks on real access problems
  (`not_a_file`/`not_writable`/`parent_not_writable`); `parent_missing`/creatable are fine.
  Keep that distinction if discovery codes change.
- Keep JavaScript minimal. Prefer HTMX attributes over custom scripts.

## Dependencies

`fastapi`, `uvicorn`, `jinja2`, `python-multipart` (HTML form parsing), `musicseed-core`
(editable path); dev group: `pytest`, `httpx`
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
