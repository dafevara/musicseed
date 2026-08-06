# Local Runtime And Operations

MusicSeed runs locally from source. Infrastructure should remain boring and inspectable.

## Runtime Pieces

- Python 3.14+ packages under `core/src/musicseed` (library), `cli/src/musicseed_cli` (CLI), and
  `web/src/musicseed_web` (local web UI).
- uv for dependency management and command execution.
- One local SQLite file for MusicSeed's own state (default
  `~/.local/share/musicseed/musicseed.db`, WAL mode) — no database server.
- Plex SQLite database as a read-only import source.
- Plex blobs SQLite database as a read-only source of sonic analysis vectors (read at query time).
- Optional Plex HTTP API for playlist creation (`core/src/musicseed/clients/plex_api.py`).
- Optional external HTTP APIs: ListenBrainz and Spotify.
- Local logs under `logs/`.

## Database

MusicSeed stores its state in a single SQLite file, configured by `database.path`
(default `~/.local/share/musicseed/musicseed.db`). The engine runs in WAL mode with foreign
keys enabled.

Commands:

```bash
uv run musicseed init-db       # creates the file (and parent dir) and tables
uv run musicseed optimize-db   # search, queue, and tag indexes
uv run musicseed status        # shows the DB path and file size
```

`init-db` creates tables. `optimize-db` creates search, queue, and tag
indexes. `ensure_schema()` applies lightweight additive updates for existing local databases.

Backup and restore are file operations: copy `musicseed.db` (plus `-wal`/`-shm` if copying
while in use). A one-shot migration from the retired Postgres setup lives at
`scripts/migrate_pg_to_sqlite.py` (`uv run scripts/migrate_pg_to_sqlite.py` from the repo
root).

## Configuration

Config lookup order:

1. `~/.config/musicseed/config.yaml`
2. `~/.musicseed.yaml`
3. `config.yaml`

Environment variables and `~` are expanded. Keep credentials out of repo-local tracked files.

## Logging

The CLI configures file logging through `core/src/musicseed/logging_config.py`.

- Timestamped run logs: `logs/musicseed_YYYYMMDD_HHMMSS.log`
- Latest run: `logs/latest.log`

When changing pipelines, log enough detail to diagnose failed batches without flooding console
output. Console output should summarize progress and outcome.

## Safe Development Commands

These are cheap and should be used before heavier checks:

```bash
python3 -m compileall -q core/src/musicseed cli/src/musicseed_cli web/src/musicseed_web
uv run ruff check src
uv run musicseed --help
```

Stateful commands should be limited during development:

```bash
uv run musicseed enrich --source listenbrainz --limit 100 --batch-size 50 --resume
uv run musicseed sonic-probe
uv run musicseed recommend --seed-id 123 --limit 20 --dry-run --explain
```

## Slow Or Risky Operations

Ask before running:

- Full Plex import on the user's real library.
- Full ListenBrainz or Spotify enrichment.
- Triggering Plex's MusicAnalysis Butler task (`sonic-refresh`, `sonic-probe --trigger-butler`).
- Any operation that writes or rewrites Plex playlists.
- Deleting or replacing the MusicSeed SQLite database file.

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
