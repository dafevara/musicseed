# Local Runtime And Operations

MusicSeed runs locally from source. Infrastructure should remain boring and inspectable.

## Runtime Pieces

- Python 3.11+ package under `src/musicseed`.
- uv for dependency management and command execution.
- PostgreSQL 16 with pgvector from `docker-compose.yml`.
- Plex SQLite database as a read-only import source.
- Optional Plex HTTP API for playlist creation.
- Optional external HTTP APIs: ListenBrainz and Spotify.
- Local logs under `logs/`.

## Database

The default Docker service uses:

- Host: `localhost`
- Port: `5432`
- Database: `musicseed`
- User: `musicseed`
- Password: `musicseed`

Commands:

```bash
docker-compose up -d
uv run musicseed init-db
uv run musicseed optimize-db
uv run musicseed status
```

`init-db` creates tables and enables pgvector. `optimize-db` creates search, queue, tag, and vector
indexes. `ensure_schema()` applies lightweight additive updates for existing local databases.

## Configuration

Config lookup order:

1. `~/.config/musicseed/config.yaml`
2. `~/.musicseed.yaml`
3. `config.yaml`

Environment variables and `~` are expanded. Keep credentials out of repo-local tracked files.

## Logging

The CLI configures file logging through `src/musicseed/logging_config.py`.

- Timestamped run logs: `logs/musicseed_YYYYMMDD_HHMMSS.log`
- Latest run: `logs/latest.log`

When changing pipelines, log enough detail to diagnose failed batches without flooding console
output. Console output should summarize progress and outcome.

## Safe Development Commands

These are cheap and should be used before heavier checks:

```bash
python3 -m compileall -q src/musicseed
uv run ruff check src
uv run musicseed --help
```

Stateful commands should be limited during development:

```bash
uv run musicseed enrich --source listenbrainz --limit 100 --batch-size 50 --resume
uv run musicseed embed --limit 10 --workers 1 --missing-only
uv run musicseed recommend --seed-id 123 --limit 20 --dry-run --explain
```

## Slow Or Risky Operations

Ask before running:

- Full Plex import on the user's real library.
- Full ListenBrainz or Spotify enrichment.
- Full-library embedding generation.
- Any operation that writes or rewrites Plex playlists.
- PostgreSQL volume deletion or data reset.

## External APIs

ListenBrainz enrichment uses recording MBIDs and should be the default enrichment path when
possible. Spotify requires credentials and text matching, so treat it as optional fallback.

HTTP clients should:

- Respect rate limits and retries.
- Use bounded concurrency.
- Commit progress in batches.
- Mark attempted tracks so interrupted jobs can resume.

## Harness Sensors

For this small project, useful sensors are intentionally simple:

- Computational sensors: compileall, Ruff, CLI help, small dry runs, limited DB commands.
- Runtime sensors: `logs/latest.log`, status coverage tables, explainable recommendation output.
- Human sensors: review playlists manually before writing to Plex.

Avoid adding CI, custom linters, or observability stacks until repeated failures justify them.
