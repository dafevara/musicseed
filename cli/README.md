# musicseed-cli

The command-line interface for [MusicSeed](../README.md). It's a thin Typer/Rich wrapper over
[`musicseed-core`](../core): every command delegates to a core service. Installs the
`musicseed-cli` command. The product web command is `musicseed` (from `api/`), not this package.

The repo-root [`install.sh`](../scripts/install.sh) puts `musicseed-cli` on your PATH
(`~/.local/bin`) alongside `musicseed` — no uv or server needed. The database is a single SQLite
file — `musicseed-cli init-db` creates it (default `~/.local/share/musicseed/musicseed.db`).

## Setup

End users: nothing to do — run [`../scripts/install.sh`](../scripts/install.sh) once, then use
`musicseed-cli` directly.

Contributors (uses [uv](https://docs.astral.sh/uv/), the development-only dependency manager):

```bash
cd cli
uv sync            # installs musicseed-core (editable) + typer/rich
uv run musicseed-cli --help
```

## Usage

```bash
# Database
musicseed-cli init-db
musicseed-cli optimize-db
musicseed-cli status                     # library + enrichment coverage

# Ingest (use --limit while exploring)
musicseed-cli import
musicseed-cli enrich --source listenbrainz --limit 100 --batch-size 50 --resume

# Recommend / create playlists
musicseed-cli recommend --seed-id 123 --limit 20 --explain
musicseed-cli playlist --name "My Mix" --seed-id 123      # prompts before writing to Plex
musicseed-cli playlists                                   # list Plex audio playlists
musicseed-cli populate --playlist "My Mix" --dry-run      # preview complementary tracks
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

## Run from the repo (optional)

To run `musicseed-cli` without the repo-root install, from inside `cli/`:

```bash
uv sync && uv run musicseed-cli --help   # contributor path (requires uv)
```

## Notes

- Logs are written under `~/.local/share/musicseed/logs/` (including `latest.log`).

See [`AGENTS.md`](AGENTS.md) for the command→service map and contributor conventions.
