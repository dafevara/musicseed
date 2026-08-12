# musicseed-cli — Agent Guide

`cli/` is the Typer command-line surface for MusicSeed. It is a **thin wrapper**: it parses
arguments, renders Rich output, prompts for confirmation on destructive Plex writes, and delegates
all real work to `musicseed-core`'s `services/` layer. No recommendation, database, or Plex logic
lives here — if you find yourself adding business logic to a command, it belongs in `core`.

Read the root `AGENTS.md` for product context and repo-wide safety rules, and `core/AGENTS.md` for
the logic this app calls. This file covers the CLI app only.

## Identity

- Distribution name: `musicseed-cli`. Import package: `musicseed_cli`.
- Installed command: **`musicseed`** → `musicseed_cli.app:app`.
- Depends on `musicseed-core` via an **editable path source** in `pyproject.toml`, so edits
  to core are picked up without reinstalling.
- Own `pyproject.toml` + `uv.lock` + `.venv`. Run `uv`/`musicseed` from inside `cli/` (or use
  `uv run --project cli musicseed …`).

## Code Map

- `src/musicseed_cli/app.py`: **app assembly only** — `app = typer.Typer(...)`, the global
  `@app.callback()` (`--version`, `--config`, logging flags → `load_config`/`set_config` +
  `setup_logging`), and a single `register_all(app)` call that attaches every command. This is the
  entry point (`musicseed_cli.app:app`); keep the `app` object importable from here.
- `src/musicseed_cli/commands/`: **one module per command**, each exposing a plain command function
  plus a `register(app)` that attaches it. `commands/__init__.py` holds `register_all(app)`, which
  registers all modules in the intended command order. Modules: `init_db`, `optimize_db`,
  `status`, `import_library`, `sonic_probe`, `sonic_refresh`, `enrich`,
  `recommend`, `playlist`, `playlists`, `populate`. To add a command, create a module with
  `register(app)` and list it in
  `commands/__init__.py`.
- `src/musicseed_cli/console.py`: the shared Rich `Console` instance (`from musicseed_cli.console
  import console`).
- `src/musicseed_cli/rendering.py`: shared recommendation-output helpers — `print_seed_table`,
  `print_recommendations_table`, `popularity_cell`, and `build_weights(...)` (assembles a
  `recommender.scoring.Weights` from the six `--w-*` options, used by `recommend`/`playlist`/`populate`).
- `src/musicseed_cli/__init__.py`: package marker.

Imports from core are unchanged from the pre-monorepo layout (`from musicseed.config import …`,
`from musicseed.services import …`, etc.).

## Commands → core service (all logic is in core)

| Command | Calls |
|---|---|
| `init-db` / `optimize-db` / `status` | `services.library.initialize_database` / `optimize_database` / `get_status` |
| `import` | `services.library.import_library` |
| `sonic-probe` (`--trigger`/`--trigger-butler` confirm before touching Plex) | `services.plex_analysis.get_sonic_status` / `probe_sonic_trigger` / `probe_butler_trigger` |
| `sonic-refresh` (`--days N`, confirms before triggering the Butler task) | `services.plex_analysis.refresh_sonic_analysis` |
| `enrich` (`--source spotify|listenbrainz`) | `services.enrichment.enrich_tracks` |
| `recommend` | `services.recommend.get_recommendations` |
| `playlist` | `get_recommendations` → confirm → `services.recommend.create_playlist` |
| `playlists` | `services.populate.list_plex_playlists` |
| `populate` | `services.populate.get_populate_recommendations` → confirm → `populate_playlist` |

## Particularities to respect

- **Thin wrapper only.** Commands validate input, build a `recommender.scoring.Weights` via
  `rendering.build_weights` from the six `--w-*` options, call one service function, and render the
  result. Keep it that way.
- **Error mapping.** Commands catch `NotFoundError` / `ConfigurationError` / `MusicSeedError` and
  translate to `console.print(...)` + `raise typer.Exit(1)`; unexpected errors are logged via
  `get_logger("cli")` to `logs/latest.log` before exiting. Follow this pattern for new commands.
- **Confirm before Plex writes.** `playlist` and `populate` generate a preview, show it, then use
  `typer.confirm(...)` before the mutating call. `populate --dry-run` skips the write entirely.
  Preserve this human-in-the-loop step for anything that mutates Plex.
- **Config is YAML** (this app's mechanism), loaded by core from `~/.config/musicseed/config.yaml`,
  `~/.musicseed.yaml`, or a **cwd-relative `./config.yaml`** — which, when running from `cli/`,
  means `cli/config.yaml`. Home-dir configs are unaffected by the monorepo move.
- **Logs land in `core/logs/`**, not `cli/logs/`, because `setup_logging` locates the nearest
  `pyproject.toml` from core's `__file__`. Don't be surprised looking for `latest.log`.

## Dependencies

`typer`, `rich`, `musicseed-core` (editable path); dev group: `pytest`.
After changing core, run `uv lock` in `cli/` so its lockfile re-resolves against the
updated app.

## Run / verify (from `cli/`)

```bash
uv sync                                  # installs core editable + typer/rich
uv run musicseed --help
uv run ruff check src
uv run pytest tests -q                   # command tests (no server, no browser, no DB)
uv run musicseed status                  # needs config (SQLite file; `init-db` creates it)
```

Note: `ruff check src` currently reports pre-existing I001/E501 issues in the older command
modules; new code must at least pass on the files it touches.

The web UI is a separate Next.js app (see `web/AGENTS.md`); the CLI has no `web` command.

Use limits when exercising slow/stateful paths:

```bash
uv run musicseed enrich --source listenbrainz --limit 100 --batch-size 50 --resume
uv run musicseed recommend --seed-id 123 --limit 20 --explain
```

If a flag here disagrees with the command module in `commands/`, trust the code and update this doc
in the same change.
