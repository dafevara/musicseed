# MusicSeed Agent Guide

MusicSeed is a personal, local-first music recommendation tool for a Plex library. Optimize for
correctness, recoverability, and simple operation on one user's machine. Do not introduce
enterprise patterns, distributed systems, or heavy process unless the existing code clearly needs
them.

This is the **root guide** for the monorepo. It covers shared context, layout, and repo-wide
rules, then routes you to the app you're working in. **Read the per-app `AGENTS.md` for details.**

## Fast Context

- Product: generate Plex playlists from seed tracks using local library metadata, popularity
  enrichment, Plex sonic analysis vectors (read at query time), and play history.
- Runtime: Python 3.12+, SQLAlchemy, SQLite (one local file). End-user install is plain
  `python3 -m venv` + `pip` (`scripts/install.sh`); uv is development-only tooling. Typer/Rich
  in the CLI.
- Platform: macOS and Linux, run from source.
- Recommendation signals (six): sonic, popularity, style, genre, era, novelty.

## Monorepo layout

Independent apps that share one core library. Each app has its own `pyproject.toml`, `uv.lock`,
and `.venv`; run `uv` commands from inside the app directory.

| Path | What | Guide |
|---|---|---|
| `core/` | `musicseed-core` — all logic (import, enrich, sonic vectors, recommender, db, config). Importable as `musicseed`. Library only, no CLI. | [`core/AGENTS.md`](core/AGENTS.md) |
| `api/` | `musicseed-api` — REST API (FastAPI, JSON) + the `musicseed` product command. Wraps core's services; consumed by the web UI over HTTP. | [`api/AGENTS.md`](api/AGENTS.md) |
| `cli/` | `musicseed-cli` — Typer CLI (`musicseed-cli`). Thin wrapper over core's services; depends on core via an editable path. | [`cli/AGENTS.md`](cli/AGENTS.md) |
| `web/` | `musicseed-web` — local web UI (Next.js + React + TypeScript, client-rendered SPA). Thin rendering layer over the API; no business logic. `npm run build` writes `web/out/`; `musicseed` serves it. | [`web/AGENTS.md`](web/AGENTS.md) |
| `mcp/` | Future surface (MCP server). Not present yet; will be a sibling app depending on `core` (and `api` if REST is the preferred transport). | — |

Shared at the repo root: `ruff.toml` (lint config for all apps), `docs/`, `data/`, `logs/`,
`scripts/` (one-shot utilities, e.g. `migrate_pg_to_sqlite.py`).

**Where logic goes:** all business logic lives in `core/` behind the surface-agnostic `services/`
layer. Multi-step orchestration (config manipulation, job lifecycle, error mapping) lives in
`api/handlers/` — surface-agnostic functions that return Pydantic models. The CLI calls core
services directly; the web UI calls the JSON API over HTTP. App surfaces (cli, web) only parse
input, call a handler or service, and format the result. If you're adding recommendation/db/Plex
logic to a surface or handler that could live in core, move it to `core/services/`.

## Harness Principles

- Prefer repo-local truth over guessing. Read the relevant file and focused doc before editing.
- Keep context small. Open the app guide and docs for the area you're touching, not everything.
- Make reversible, local changes. This project controls a personal music database and Plex
  library, so destructive operations require explicit user intent.
- Verify cheaply first. Compile and lint before running DB, network, or audio-heavy commands.
- Preserve home-project simplicity. A clear script, README note, or focused doc usually beats a
  new framework.

## Docs Routing

- Product intent and scope: `docs/product/overview.md`.
- Harness strategy and maintenance loop: `docs/harness-engineering.md`.
- Music/recommendation domain concepts: `docs/domain/music-recommendation.md`.
- Local services, config, logs, and verification commands: `docs/infra/local-runtime.md`.
- Setup/job failure recovery (Plex detection, tokens, ports, providers, sonic, backup):
  `docs/infra/troubleshooting.md`.
- Seed matching, candidate generation, scoring, playlist selection: `docs/resolvers/recommendation-resolvers.md`.
- Visual dependency/workflow explainer (self-contained HTML, keep in sync when deps change):
  `docs/musicseed-dependency-architecture.html`.
- Historical plan and architecture: `docs/implementation-plan.md`, `docs/ard/001-initial-system-design.md`
  (partially superseded by `docs/ard/002-sonic-vectors-at-query-time.md`).

The docs in `docs/` also render as a MkDocs Material site (config `mkdocs.yml`); verify it with
`.venv-docs/bin/mkdocs build --strict` from the repo root.

## Shared Commands

```bash
cd cli   && uv run musicseed-cli status   # CLI from cli/ (SQLite file, no server needed)
cd api   && uv run ruff check src     # per-app lint (ruff.toml is shared at root)
cd core  && uv run ruff check src
cd api   && uv run pytest tests -q    # offline API suite (stubs Plex/DB)
cd web   && npx tsc --noEmit          # type-check the Next.js surface
python3 -m compileall -q core/src/musicseed cli/src/musicseed_cli api/src/musicseed_api
uv venv --python 3.12 .venv-docs && uv pip install --python .venv-docs -r docs/requirements-docs.txt  # one-time docs env
.venv-docs/bin/mkdocs build --strict # build the MkDocs Material docs site; fails on broken links/refs
```

The MusicSeed database is a single SQLite file (default
`~/.local/share/musicseed/musicseed.db`, WAL mode). `musicseed-cli init-db` creates it; backup is
copying the file. The web wizard also initializes it on first run.

App-specific commands and verification live in each app's `AGENTS.md`.

## Repo-wide Safety Rules

- Do not delete or rewrite `data/`, `logs/`, local Plex databases, or the MusicSeed SQLite
  database file unless the user explicitly asks.
- Do not run full-library import or enrichment jobs without user confirmation. Use
  `--limit`, `--dry-run`, and `--resume` when exploring behavior.
- Do not expose Plex tokens, Spotify credentials, database passwords, local library file paths, or
  logs containing secrets.
- Treat external APIs as optional and rate-limited. ListenBrainz is preferred when MBIDs exist;
  Spotify is a credentialed fallback.
- Keep `.DS_Store`, local databases, logs, and other machine-local artifacts out of commits unless
  intentionally asked to track them.

## Change Guidelines

- Match existing style: type hints, SQLAlchemy ORM, Pydantic models, Typer commands, Rich output.
- Keep `core/services/` surface-agnostic (no Typer/HTTP framework, no user-facing `print`); return
  result models and raise typed exceptions for surfaces to map.
- Schema changes: additive migrations or `ensure_schema()`-style compatibility for this local
  project unless a real migration system is introduced intentionally.
- Recommendation changes: preserve explainability — update score breakdowns and the resolver docs
  when adding a signal.
- Docs/code drift: if a documented command or flag disagrees with the code, trust the code and fix
  the doc in the same change.
