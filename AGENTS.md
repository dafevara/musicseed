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
- Runtime: Python 3.14+, SQLAlchemy, SQLite (one local file), uv. Typer/Rich in the CLI.
- Platform: macOS on Apple Silicon, run from source.
- Recommendation signals (six): sonic, popularity, style, genre, era, novelty.

## Monorepo layout

Independent apps that share one core library. Each app has its own `pyproject.toml`, `uv.lock`,
and `.venv`; run `uv` commands from inside the app directory.

| Path | What | Guide |
|---|---|---|
| `core/` | `musicseed-core` — all logic (import, enrich, sonic vectors, recommender, db, config). Importable as `musicseed`. Library only, no CLI. | [`core/AGENTS.md`](core/AGENTS.md) |
| `cli/` | `musicseed-cli` — Typer CLI (`musicseed`). Thin wrapper over core's services; depends on core via an editable path. | [`cli/AGENTS.md`](cli/AGENTS.md) |
| `api/`, `mcp/`, `web/` | Future surfaces (HTTP API, MCP server, frontend). Not present yet; each will be a sibling app depending on `core`. | — |

Shared at the repo root: `ruff.toml` (lint config for all apps), `docs/`, `data/`, `logs/`,
`scripts/` (one-shot utilities, e.g. `migrate_pg_to_sqlite.py`).

**Where logic goes:** all business logic lives in `core/` behind the surface-agnostic `services/`
layer. App surfaces (cli, future api/mcp) only parse input, call a service, and format the result.
If you're adding recommendation/db/Plex logic to a surface, move it to `core`.

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
- Seed matching, candidate generation, scoring, playlist selection: `docs/resolvers/recommendation-resolvers.md`.
- Visual dependency/workflow explainer (self-contained HTML, keep in sync when deps change):
  `docs/musicseed-dependency-architecture.html`.
- Historical plan and architecture: `docs/implementation-plan.md`, `docs/ard/001-initial-system-design.md`
  (partially superseded by `docs/ard/002-sonic-vectors-at-query-time.md`).

## Shared Commands

```bash
cd cli   && uv run musicseed status  # run the CLI from cli/ (SQLite file, no server needed)
cd core  && uv run ruff check src    # per-app lint (ruff.toml is shared at root)
python3 -m compileall -q core/src/musicseed cli/src/musicseed_cli
```

The MusicSeed database is a single SQLite file (default
`~/.local/share/musicseed/musicseed.db`, WAL mode). `musicseed init-db` creates it; backup is
copying the file.

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
