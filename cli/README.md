# musicseed-cli

The command-line interface for [MusicSeed](../README.md). It's a thin Typer/Rich wrapper over
[`musicseed-core`](../core): every command delegates to a core service. Installs the `musicseed`
command.

Run commands from this directory (or prefix with `uv run --project cli`). The database is a
single SQLite file — `musicseed init-db` creates it (default
`~/.local/share/musicseed/musicseed.db`); no server is needed.

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
uv run musicseed enrich --source listenbrainz --limit 100 --batch-size 50 --resume

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

Recommendations read Plex's sonic analysis vectors directly from the Plex blobs database, so
tracks must be sonically analyzed by Plex first — check coverage with `musicseed sonic-probe` and
trigger analysis with `musicseed sonic-refresh`.

## Configuration

The CLI loads YAML config from the first existing path:

- `~/.config/musicseed/config.yaml`
- `~/.musicseed.yaml`
- `config.yaml` (relative to the current directory, i.e. `cli/config.yaml` when run from here)

Copy the repo root [`config.example.yaml`](../config.example.yaml) to one of those paths and
fill in values. Prefer `${PLEX_TOKEN}` / `${SPOTIFY_CLIENT_*}` over hard-coded secrets.
**Never commit a real `config.yaml`.**

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
