# musicseed-cli

The command-line interface for [MusicSeed](../README.md). It's a thin Typer/Rich wrapper over
[`musicseed-core`](../core): every command delegates to a core service. Installs the
`musicseed-cli` command. The product web command is `musicseed` (from `api/`), not this package.

Run commands from this directory (or prefix with `uv run --project cli`). The database is a
single SQLite file — `musicseed-cli init-db` creates it (default
`~/.local/share/musicseed/musicseed.db`); no server is needed.

## Setup

```bash
cd cli
uv sync            # installs musicseed-core (editable) + typer/rich
uv run musicseed-cli --help
```

## Usage

```bash
# Database
uv run musicseed-cli init-db
uv run musicseed-cli optimize-db
uv run musicseed-cli status                     # library + enrichment coverage

# Ingest (use --limit while exploring)
uv run musicseed-cli import
uv run musicseed-cli enrich --source listenbrainz --limit 100 --batch-size 50 --resume

# Recommend / create playlists
uv run musicseed-cli recommend --seed-id 123 --limit 20 --explain
uv run musicseed-cli playlist --name "My Mix" --seed-id 123      # prompts before writing to Plex
uv run musicseed-cli playlists                                   # list Plex audio playlists
uv run musicseed-cli populate --playlist "My Mix" --dry-run      # preview complementary tracks
```

`recommend`, `playlist`, and `populate` accept per-signal weights (`--w-sonic`, `--w-popularity`,
`--w-style`, `--w-genre`, `--w-era`, `--w-novelty`), year filters (`--year-min`/`--year-max`),
`--artist-max`, and `--min-score`. `playlist` and `populate` prompt for confirmation before
writing to Plex; `populate --dry-run` previews without writing.

Recommendations read Plex's sonic analysis vectors directly from the Plex blobs database, so
tracks must be sonically analyzed by Plex first — check coverage with `musicseed-cli sonic-probe`
and trigger analysis with `musicseed-cli sonic-refresh`.

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

To run `musicseed-cli` from anywhere without `uv run`:

```bash
uv tool install --editable ./cli      # from the repo root
```

## Notes

- Logs are written under `~/.local/share/musicseed/logs/` (including `latest.log`).

See [`AGENTS.md`](AGENTS.md) for the command→service map and contributor conventions.
