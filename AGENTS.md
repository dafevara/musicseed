# MusicSeed Agent Guide

MusicSeed is a personal, local-first music recommendation CLI for a Plex library.
Optimize for correctness, recoverability, and simple operation on one user's machine.
Do not introduce enterprise patterns, distributed systems, or heavy process unless the
existing code clearly needs them.

## Fast Context

- Product: generate Plex playlists from seed tracks using local library metadata, popularity
  enrichment, audio embeddings, and play history.
- Runtime: Python 3.11+, Typer/Rich CLI, SQLAlchemy, PostgreSQL 16 with pgvector, uv.
- Platform: macOS on Apple Silicon, run from source.
- Primary package: `src/musicseed`.
- Existing docs: start with `README.md`, then use the focused docs under `docs/`.
- Current authoritative design record: `docs/ard/001-initial-system-design.md`.

## Harness Principles

These instructions follow a lightweight harness-engineering style: give agents just enough
project memory, context routing, tools, and verification paths to make useful changes safely.

- Prefer repo-local truth over guessing. Read the relevant file and focused doc before editing.
- Keep context small. Open the docs for the area you are touching instead of loading every doc.
- Make reversible, local changes. This project controls a personal music database and Plex
  library, so destructive operations require explicit user intent.
- Verify cheaply first. Compile and lint before running DB, network, or audio-heavy commands.
- Preserve home-project simplicity. A clear script, README note, or focused doc is often better
  than a new framework.

## Code Map

- `src/musicseed/cli.py`: Typer commands and user-facing command flow.
- `src/musicseed/config.py`: YAML config loading and environment expansion.
- `src/musicseed/db/models.py`: SQLAlchemy tables for artists, albums, tracks, tags, history,
  stats, playlists, popularity fields, and embeddings.
- `src/musicseed/db/session.py`: engine/session setup, schema initialization, additive schema
  repair, and indexes.
- `src/musicseed/importers/plex.py`: Plex SQLite metadata import.
- `src/musicseed/enrichers/`: ListenBrainz, Spotify, and MusicBrainz clients plus the shared
  enrichment pipeline.
- `src/musicseed/embeddings/`: audio embedding generation pipeline and Essentia wrapper.
- `src/musicseed/recommender/`: seed resolution, candidate pools, scoring, and playlist ranking.
- `docker-compose.yml`: local PostgreSQL + pgvector service.

## Docs Routing

- Product intent and scope: `docs/product/overview.md`.
- Harness strategy and maintenance loop: `docs/harness-engineering.md`.
- Music/recommendation domain concepts: `docs/domain/music-recommendation.md`.
- Local services, config, logs, and verification commands: `docs/infra/local-runtime.md`.
- Seed matching, candidate generation, scoring, and playlist selection: `docs/resolvers/recommendation-resolvers.md`.
- Historical plan and architecture: `docs/implementation-plan.md` and `docs/ard/001-initial-system-design.md`.

## Common Commands

Use these from the repository root.

```bash
uv run musicseed --help
uv run musicseed status
uv run ruff check src
python3 -m compileall -q src/musicseed
docker-compose up -d
uv run musicseed init-db
uv run musicseed optimize-db
```

For slow or stateful operations, use limits while developing:

```bash
uv run musicseed enrich --source listenbrainz --limit 100 --batch-size 50 --resume
uv run musicseed embed --limit 10 --workers 1 --missing-only
uv run musicseed recommend --seed-id 123 --limit 20 --dry-run --explain
```

If a command shown here does not exist or its flags differ from code, trust the code and update
the docs in the same change.

## Safety Rules

- Do not delete or rewrite `data/`, `logs/`, local Plex databases, or PostgreSQL volumes unless
  the user explicitly asks.
- Do not run full-library import, enrichment, or embedding jobs without user confirmation.
- Do not expose Plex tokens, Spotify credentials, database passwords, local file paths from the
  user's library, or logs containing secrets.
- Use `--limit`, `--dry-run`, `--resume`, and low worker counts when exploring behavior.
- Treat external APIs as optional and rate-limited. ListenBrainz enrichment is preferred when
  MBIDs are available; Spotify is a fallback requiring credentials.
- Keep `.DS_Store`, local databases, logs, and other machine-local artifacts out of committed
  changes unless the user has intentionally asked to track them.

## Change Guidelines

- Match existing style: dataclasses, type hints, SQLAlchemy ORM, Typer commands, Rich output.
- Keep CLI behavior explicit and recoverable. Prefer idempotent commands and resumable pipelines.
- For schema changes, use additive migrations or `ensure_schema()`-style compatibility for this
  local project unless a larger migration system is introduced intentionally.
- For recommendation changes, preserve explainability. Update score breakdowns or resolver docs
  when adding a signal.
- For long-running jobs, log actionable details to `logs/latest.log` and keep console output concise.
- Add tests when a change affects matching, scoring, filtering, or data conversion. If tests are
  not present yet, use focused pure-function tests rather than broad integration tests.

## Verification Checklist

Before handing work back, run the smallest useful subset:

- Syntax/import sanity: `python3 -m compileall -q src/musicseed`.
- Lint when dependencies are available: `uv run ruff check src`.
- CLI smoke check: `uv run musicseed --help`.
- DB-related changes: `docker-compose up -d`, then `uv run musicseed init-db` or `status` when safe.
- Recommendation changes: run a limited dry run with `--dry-run --explain` if local data exists.

Report any command that could not be run and why.
