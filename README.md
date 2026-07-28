# MusicSeed

MusicSeed is a personal music recommendation tool for a local Plex music library. It imports Plex
metadata into PostgreSQL, enriches tracks with popularity signals, reads Plex's sonic analysis
vectors for similarity, produces seed-based recommendations, and writes them back to Plex as
playlists.

This is a DIY, home-usage project. The design favors simple local operation, recoverable batch
jobs, and explainable recommendations over large-scale product architecture.

## What It Does

- Imports artists, albums, tracks, tags, file paths, MusicBrainz IDs, and play history from the
  Plex SQLite database into PostgreSQL 16.
- Enriches popularity from ListenBrainz by MusicBrainz recording MBID, with Spotify as an optional
  fallback.
- Uses Plex's own sonic analysis vectors (50-dimensional, read in memory at query time) for sonic
  similarity — MusicSeed generates no embeddings and stores no vectors.
- Recommends tracks from six signals: sonic similarity, popularity proximity, style, genre, era,
  and novelty.
- Creates and populates Plex playlists from recommendations via a Typer CLI with Rich output.

## Scope

MusicSeed is not a Plex replacement, streaming server, social product, or multi-user platform. It
runs from source on the owner's machine against the owner's Plex library.

## License And Security

- License: [MIT](LICENSE)
- Security policy and private reporting: [SECURITY.md](SECURITY.md)
- Example config (no secrets): [config.example.yaml](config.example.yaml)

Do not commit real `config.yaml`, `.env`, database dumps, or logs. Keep Plex tokens and API
credentials in env vars or an untracked local config.

## Repository Layout

MusicSeed is a monorepo of independent apps that share one core library. Each app has its own
`pyproject.toml` and its own `uv.lock`/virtualenv.

- **[`core/`](core/README.md)** — `musicseed-core`, the reusable library (import, enrichment,
  sonic vectors, recommender, db, config). Importable as `musicseed`. All logic lives here; no UI.
- **[`cli/`](cli/README.md)** — `musicseed-cli`, the Typer command-line app. Depends on `core` via
  an editable path dependency. **This is how you use MusicSeed today.**
- `api/`, `mcp/`, `web/` — future surfaces (HTTP API, MCP server, frontend). Not present yet; each
  will be a sibling app that also depends on `core`.

Shared infrastructure (`docker-compose.yml`, `docs/`, `ruff.toml`) lives at the repo root.

## Requirements

- macOS on Apple Silicon
- Python 3.11+ and uv
- Docker (or another PostgreSQL 16 + pgvector setup)
- Plex Media Server with a music library
- Optional Spotify API credentials for fallback enrichment

## Quick Start

```bash
docker-compose up -d          # shared Postgres + pgvector, from the repo root

cd cli                        # the CLI app
uv sync
uv run musicseed --help
uv run musicseed status
```

Full CLI usage and configuration: **[`cli/README.md`](cli/README.md)**.
Using the core library as a dependency: **[`core/README.md`](core/README.md)**.

## For Coding Agents

`AGENTS.md` at the repo root is the provider-neutral harness entry point; each app has its own
`AGENTS.md` with a code map and app-specific conventions. Focused documentation lives under
`docs/`:

- `docs/product/overview.md`
- `docs/domain/music-recommendation.md`
- `docs/infra/local-runtime.md`
- `docs/resolvers/recommendation-resolvers.md`

## Logs And Data

Logs are written under `core/logs/` (including `latest.log`) — the logger anchors to the core
package's location. Local Plex database copies, PostgreSQL volumes, logs, and credentials are
machine-local artifacts and are not portable project source.
