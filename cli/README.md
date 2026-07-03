# musicseed-cli

The command-line interface for [MusicSeed](../README.md). It's a thin Typer/Rich wrapper over
[`musicseed-core`](../core): every command delegates to a core service. Installs the `musicseed`
command.

Run commands from this directory (or prefix with `uv run --project cli`). Start the shared
database from the repo root first (`docker-compose up -d`).

## Setup

```bash
cd cli
uv sync            # installs musicseed-core (editable) + typer/rich
uv run musicseed --help
```

## Usage

```bash
# Database
uv run musicseed init-db
uv run musicseed optimize-db
uv run musicseed status                     # library + enrichment coverage

# Ingest (use --limit while exploring)
uv run musicseed import
uv run musicseed import-plex-sonic          # import existing Plex sonic vectors
uv run musicseed enrich --source listenbrainz --limit 100 --batch-size 50 --resume
uv run musicseed embed --limit 10 --workers 1 --missing-only

# Recommend / create playlists
uv run musicseed recommend --seed-id 123 --limit 20 --explain
uv run musicseed playlist --name "My Mix" --seed-id 123      # prompts before writing to Plex
uv run musicseed playlists                                   # list Plex audio playlists
uv run musicseed populate --playlist "My Mix" --dry-run      # preview complementary tracks
```

`recommend`, `playlist`, and `populate` accept per-signal weights (`--w-sonic`, `--w-popularity`,
`--w-style`, `--w-genre`, `--w-era`, `--w-novelty`), year filters (`--year-min`/`--year-max`),
`--artist-max`, and `--min-score`. `playlist` and `populate` prompt for confirmation before
writing to Plex; `populate --dry-run` previews without writing.

## Configuration

The CLI loads YAML config from the first existing path:

- `~/.config/musicseed/config.yaml`
- `~/.musicseed.yaml`
- `config.yaml` (relative to the current directory, i.e. `cli/config.yaml` when run from here)

Minimal example:

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
  auto_download_model: true
```

Environment variables and `~` are expanded by the loader. Writing playlists to Plex requires
`plex.token`.

## Install as a global tool (optional)

To run `musicseed` from anywhere without `uv run`:

```bash
uv tool install --editable ./cli      # from the repo root
```

## Notes

- Logs are written under `core/logs/` (including `latest.log`) — the logger anchors to the core
  package's location, not the CLI's.

See [`AGENTS.md`](AGENTS.md) for the command→service map and contributor conventions.
