# MusicSeed

MusicSeed is a personal music recommendation CLI for a local Plex music library. It imports
Plex metadata into PostgreSQL, enriches tracks with popularity signals, generates audio
embeddings, and produces seed-based recommendations. Writing recommendations back to Plex as
playlists is planned but not implemented yet (`recommend --playlist` prints a pending notice).

This is a DIY, home-usage project. The design favors simple local operation, recoverable batch
jobs, and explainable recommendations over large-scale product architecture.

## What It Does

- Imports artists, albums, tracks, tags, file paths, MusicBrainz IDs, and play history from the
  Plex SQLite database.
- Stores library data in PostgreSQL 16 with pgvector.
- Enriches popularity from ListenBrainz by MusicBrainz recording MBID, with Spotify as an optional
  fallback.
- Generates or imports 200-dimensional stored audio vectors for sonic similarity.
- Recommends tracks from multiple signals: sonic similarity, popularity proximity, mood, style,
  genre, era, and novelty.
- Provides a Typer CLI with Rich output.

## Scope

MusicSeed is not a Plex replacement, streaming server, social product, web app, or multi-user
platform. It is meant to run from source on the owner machine against the owner's Plex library.

## Requirements

- macOS on Apple Silicon
- Python 3.11+
- uv
- Docker or another PostgreSQL 16 + pgvector setup
- Plex Media Server with a music library
- Optional Spotify API credentials for fallback enrichment

## Quick Start

Start the local database:

```bash
docker-compose up -d
```

Install and inspect the CLI:

```bash
uv run musicseed --help
```

Initialize the database:

```bash
uv run musicseed init-db
uv run musicseed optimize-db
```

Import the Plex library:

```bash
uv run musicseed import
```

Check current coverage:

```bash
uv run musicseed status
```

Run limited enrichment first:

```bash
uv run musicseed enrich --source listenbrainz --limit 100 --batch-size 50 --resume
```

Generate a limited embedding batch first:

```bash
uv run musicseed embed --limit 10 --workers 1 --missing-only
```

Or import existing Plex sonic analysis from the local Plex blobs database:

```bash
uv run musicseed import-plex-sonic
```

Try recommendations without writing a playlist:

```bash
uv run musicseed recommend --seed-id 123 --limit 20 --dry-run --explain
```

## Configuration

MusicSeed loads YAML config from the first existing path:

- `~/.config/musicseed/config.yaml`
- `~/.musicseed.yaml`
- `config.yaml`

Minimal local example:

```yaml
database:
  host: localhost
  port: 5432
  name: musicseed
  user: musicseed
  password: musicseed

plex:
  url: http://localhost:32400
  token: ${PLEX_TOKEN}
  library: Music
  db_path: "~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"

spotify:
  client_id: ${SPOTIFY_CLIENT_ID}
  client_secret: ${SPOTIFY_CLIENT_SECRET}

embedding:
  model: essentia
  # Optional. By default MusicSeed downloads this once to
  # ~/.cache/musicseed/models/msd-musicnn-1.pb.
  model_path: ""
  auto_download_model: true
```

Environment variables and `~` are expanded by the config loader.

## Development

Useful checks:

```bash
python3 -m compileall -q src/musicseed
uv run ruff check src
uv run musicseed --help
```

The repository includes `AGENTS.md` for coding agents. Use it as the provider-neutral harness
entry point. Focused documentation lives under `docs/`:

- `docs/product/overview.md`
- `docs/domain/music-recommendation.md`
- `docs/infra/local-runtime.md`
- `docs/resolvers/recommendation-resolvers.md`

## Logs And Data

Logs are written under `logs/`, including `logs/latest.log`. Local Plex database copies,
PostgreSQL volumes, logs, and credentials are machine-local artifacts and should not be treated
as portable project source.
