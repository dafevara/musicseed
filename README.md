# MusicSeed

MusicSeed is a personal music recommendation tool for a local Plex music library. It imports Plex
metadata into a local SQLite database, enriches tracks with popularity signals, reads Plex's
sonic analysis vectors for similarity, produces seed-based recommendations, and writes them back
to Plex as playlists.

This is a DIY, home-usage project. The design favors simple local operation, recoverable batch
jobs, and explainable recommendations over large-scale product architecture.

## What It Does

- Imports artists, albums, tracks, tags, file paths, MusicBrainz IDs, and play history from the
  Plex SQLite database into one local SQLite file (default
  `~/.local/share/musicseed/musicseed.db`) — no database server required.
- Enriches popularity from ListenBrainz by MusicBrainz recording MBID (free user token required),
  with Spotify as a credentialed fallback.
- Uses Plex's own sonic analysis vectors (50-dimensional, read in memory at query time) for sonic
  similarity — MusicSeed generates no embeddings and stores no vectors.
- Recommends tracks from six signals: sonic similarity, popularity proximity, style, genre, era,
  and novelty.
- Creates and populates Plex playlists from recommendations.

## Scope

MusicSeed is not a Plex replacement, streaming server, social product, or multi-user platform. It
runs from source on the owner's machine against the owner's Plex library.

## Requirements

- Python 3.12+ (with `venv` and `pip`, both included in standard Python installs)
- SQLite 3 — MusicSeed reads the Plex database and stores its own database as SQLite files; no
  database server required.
- Node.js and npm (needed to **install** / rebuild the web UI, not to run it)
- Plex Media Server with a music library (ideally already sonically analyzed)
- Optional Spotify API credentials for fallback enrichment

macOS and Linux are supported. Windows is untested.

## Install

### Release archive

Download the source zip or tar.gz from
[Releases](https://github.com/dafevara/musicseed/releases), unpack it, then:

```bash
cd MusicSeed-*
./scripts/install.sh
musicseed
```

### Install from source

```bash
git clone https://github.com/dafevara/musicseed.git
cd MusicSeed
./scripts/install.sh
musicseed
```

Then open `http://127.0.0.1:8789`. `install.sh` creates a Python virtualenv (`.venv/`) with the
core library and API installed, builds the static UI, and puts `musicseed` on your PATH via a
symlink in `~/.local/bin`. After that, runtime is Python only — Node is not required to start
the app.

On first run the setup wizard (`/setup`) walks you through setup:

1. **Discover your Plex server** — local-network discovery (GDM + SSDP), with cross-subnet lookup
   via `plex.tv` when you supply a Plex token. A manual URL is available as a fallback.
2. **Confirm the music library and database paths** — the wizard pre-fills the Plex music library
   and the on-disk Plex database paths and lets you correct them.
3. **Initialize the MusicSeed database** — creates the SQLite file and schema.
4. **Import and enrich** — optionally runs library import and ListenBrainz enrichment (Spotify is
   an optional credentialed fallback). Work runs as resumable jobs with progress.

After setup you land on a dashboard showing Plex health, import/enrichment coverage, and job
state, with recommendation and playlist pages once the library is imported. A persistent
**Settings** view (`/settings`) holds your Plex URL/token/library, database paths, and Spotify
credentials; it saves without starting any import or initialization.

`musicseed --open` launches the browser. `musicseed --no-ui` serves JSON only.

See [`docs/product/overview.md`](docs/product/overview.md) for the intended flows and
[`docs/infra/troubleshooting.md`](docs/infra/troubleshooting.md) when something goes wrong.

Contributor hot reload (API + `next dev`) is `./scripts/dev.sh` — not the user path.

## CLI (advanced)

The Typer CLI is the power-user surface. It needs no Node, no server, and no browser — and no uv:
`install.sh` puts `musicseed-cli` on your PATH alongside `musicseed`.

```bash
musicseed-cli init-db                            # create the SQLite database
musicseed-cli import                             # import Plex metadata (use --limit to explore)
musicseed-cli enrich --source listenbrainz --limit 100 --resume
musicseed-cli recommend --seed-id 123 --limit 20 --explain
musicseed-cli playlist --name "My Mix" --seed-id 123   # prompts before writing to Plex
```

Full CLI usage and configuration: **[`cli/README.md`](cli/README.md)**.
Using the core library as a dependency: **[`core/README.md`](core/README.md)**.

Contributors working on the CLI itself use [uv](https://docs.astral.sh/uv/) (the development-only
dependency manager): `cd cli && uv sync && uv run musicseed-cli --help`.

## Repository Layout

MusicSeed is a monorepo of independent apps that share one core library. Each app has its own
`pyproject.toml` and its own `uv.lock`/virtualenv.

- **[`core/`](core/README.md)** — `musicseed-core`, the reusable library (import, enrichment,
  sonic vectors, recommender, db, config). Importable as `musicseed`. All logic lives here; no UI.
- **[`api/`](api/AGENTS.md)** — FastAPI JSON REST API plus the `musicseed` product command
  (serves API + static UI on port 8789).
- **[`web/`](web/AGENTS.md)** — `musicseed-web`, the Next.js + React web UI. Thin rendering
  layer; `npm run build` writes a static export the API serves.
- **[`cli/`](cli/README.md)** — `musicseed-cli`, the Typer command-line app. Depends on `core`
  via an editable path dependency. No API dependency.
- `mcp/` — future surface (MCP server). Not present yet.

Shared infrastructure (`docs/`, `ruff.toml`, `scripts/`) lives at the repo root.

## License And Security

- License: [MIT](LICENSE)
- Security policy and private reporting: [SECURITY.md](SECURITY.md)
- Example config (no secrets): [config.example.yaml](config.example.yaml)

Do not commit real `config.yaml`, `.env`, database dumps, or logs. Keep Plex tokens and API
credentials in env vars or an untracked local config.

## Logs And Data

Logs are written under `~/.local/share/musicseed/logs/` (including `latest.log`). Local Plex
database copies, the MusicSeed SQLite database, logs, and credentials are machine-local
artifacts and are not portable project source. Backup of MusicSeed state is copying the single
SQLite file.

## For Coding Agents

`AGENTS.md` at the repo root is the provider-neutral harness entry point; each app has its own
`AGENTS.md` with a code map and app-specific conventions. Focused documentation lives under
`docs/`:

- `docs/product/overview.md`
- `docs/infra/local-runtime.md`
- `docs/infra/troubleshooting.md`
- `docs/domain/music-recommendation.md`
- `docs/resolvers/recommendation-resolvers.md`
- `docs/musicseed-dependency-architecture.html`
