# musicseed-core — Agent Guide

`core/` is the reusable library that holds **all** of MusicSeed's logic: Plex import, metadata
enrichment, the recommender, database access, and configuration. It has no
user interface. Every app surface (the `cli/`, `api/`, `web/`, and future `mcp/`) depends on
this package and drives it through the `services/` layer.

Read the root `AGENTS.md` first for product context, monorepo layout, and repo-wide safety rules.
This file covers the core library only.

## Identity

- Distribution name: `musicseed-core`. **Import name: `musicseed`** (e.g. `from musicseed.services
  import recommend`). Distribution and import names differ on purpose — keep the import name.
- Library only: **no `[project.scripts]`**, no Typer/Rich CLI command flow. Progress output uses
  `rich` (see below), but there is no console command here.
- Own `pyproject.toml` + `uv.lock` + `.venv`. Run `uv` commands from inside `core/`.

## Architecture: the `services/` seam

`services/` is the **surface-agnostic application layer** — this is the public API of core, and the
only layer app surfaces should call. Each service function:

- opens and closes its own DB session via the `get_session()` context manager,
- accepts plain kwargs (plus a `recommender.scoring.Weights` object where relevant),
- returns a **Pydantic result model**, and
- raises typed exceptions (`NotFoundError`, `ConfigurationError`, `clients.plex_api.PlexAPIError`)
  that a surface maps to its own error convention.

Service entry points:

- `services/library.py`: `initialize_database`, `optimize_database`, `import_library`,
  `get_status`, `get_import_coverage` (Plex vs local artist/album/track counts).
- `services/discovery.py`: `discover` — read-only local environment probe (MusicSeed DB path,
  Plex library/blobs DB candidates, Plex server reachability/auth/library). Returns frozen
  Pydantic models with machine-readable `Reason` codes; expected failures are data, not
  exceptions. Accepts per-call overrides (never mutates global config) and never includes the
  Plex token in results. `read_plex_token` reads a token from the local Plex install
  (`Preferences.xml` → `PlexOnlineToken`, falling back to `.LocalAdminToken`); `discover` uses
  it when no token is configured and reports `plex_server.token_source`. Also reports
  `enrichers` (Spotify credential and ListenBrainz token presence), `missing_inputs`
  (machine-readable keys like `plex_token`, `enrichment_credentials`, `plex_unreachable`,
  `db_location`), and a derived `first_run` status (`no_config` / `db_missing` /
  `library_empty`; no persisted flag). The setup wizard / dashboard consume this.
- `services/plex_discovery.py`: `discover_plex_servers` — passive, read-only Plex discovery.
  Local network via GDM multicast (`239.0.0.250:32414`) + SSDP fallback
  (`239.255.255.250:1900`, stdlib `socket` only), plus — when a Plex token is supplied —
  cross-subnet discovery via `plex.tv/api/resources` (httpx). Returns
  `list[DiscoveredPlexServer]` deduplicated by address (empty when nothing responds, never
  raises). A separate, opt-in probe — not part of `discovery.discover()`. The first-run
  wizard consumes it.
- `services/enrichment.py`: `enrich_tracks` (**calls `asyncio.run()` internally — never call it
  from inside a running event loop; offload to a thread**).
- `services/recommend.py`: `get_recommendations`, `create_playlist`.
- `services/populate.py`: `list_plex_playlists`, `get_populate_recommendations`,
  `populate_playlist` — keyed by Plex playlist `rating_key`, not title.
- `services/plex_analysis.py`: `get_sonic_status`, `probe_sonic_trigger`,
  `probe_butler_trigger`, `refresh_album`, `refresh_sonic_analysis` — inspect Plex sonic
  analysis coverage over the HTTP API (`musicAnalysisVersion`) and trigger it on demand via
  `POST /butler/MusicAnalysis` (proven to work; per-item `analyze` does NOT trigger sonic
  analysis). The Butler task always processes Plex's whole pending backlog; date windows only
  scope watching/reporting.

## Code Map

- `config.py`: Pydantic YAML config + `${ENV}`/`~` expansion. `get_config()`/`set_config()`/
  `load_config()`/`get_config_path()` global singleton. `get_config_path()` returns the resolved
  config file path (or `None` when no file was found) — discovery uses it for the `no_config`
  first-run signal. This is the CLI's config mechanism; future apps may populate
  the same `Config` from `.env` instead.
- `exceptions.py`: `MusicSeedError` (base), `ConfigurationError`, `NotFoundError`.
- `logging_config.py`: `setup_logging`/`get_logger`. Default log dir is
  `~/.local/share/musicseed/logs/` (or `$XDG_DATA_HOME/musicseed/logs`). Pass `log_dir` to
  override.
- `db/models.py`: SQLAlchemy 2.0 ORM (Artist, Album, Track, tag tables, play history, stats,
  playlists). No vector columns: sonic vectors are not stored.
- `db/session.py`: `get_engine` (SQLite, sets `journal_mode=WAL` + `foreign_keys=ON` on
  connect), `get_session_factory` (`expire_on_commit=False`), `get_session`
  (commit/rollback/close context manager), `init_db` (creates the DB file's parent dir),
  `ensure_schema` (additive migrations via `PRAGMA table_info`), `create_indexes`,
  `reset_engine` (dispose engine — the hook for tests/config reload).
- `importers/plex.py`: Plex SQLite metadata import. Track years fall back to the album year when
  Plex doesn't set one on the track row.
- `enrichers/`: ListenBrainz and Spotify clients + the async enrichment pipeline. (The old
  MusicBrainz MBID→Spotify cross-reference client was removed; it was never wired in.)
- `sonic.py`: Plex sonic analysis vectors read at query time from the Plex blobs DB into an
  in-memory L2-normalized matrix (`SonicVectors`, keyed by `plex_id`). Lazy global cache via
  `get_sonic_vectors()` / `reset_sonic_vectors()`; raises `NotFoundError` when the Plex databases
  are unavailable.
- `recommender/`: `scoring.py` (`Weights`, `ScoreBreakdown`, `SeedProfile`, `calculate_score`),
  `candidates.py` (`build_candidate_pool`), `playlist.py` (`Recommendation`, `recommend_tracks`,
  `resolve_seed_tracks` — raises `ValueError` on unresolved seeds), `populate.py`
  (`PopulateMethod = "average" | "frequency"`, `populate_playlist_recommendations`).
- `clients/plex_api.py`: thin synchronous Plex HTTP client (httpx). Raises `PlexAPIError`;
  `check_connection()` is the non-raising probe used by discovery/setup flows.

## Particularities to respect

- **Result models embed raw ORM objects.** `Recommendation`, `RecommendationResult`, etc. use
  `model_config = {"arbitrary_types_allowed": True}` and hold live SQLAlchemy `Track` objects, so
  they are **not directly JSON-serializable**. The API surface (`api/routes/`) must project
  `Track` into DTOs — see `routes/recommend.py` for the pattern. Sessions use
  `expire_on_commit=False` and eager `selectinload`, so returned `Track`s stay usable after
  the session closes — preserve both if you touch loading.
- **Recommendation signals are exactly six**: sonic, popularity, style, genre, era, novelty. There
  is no "mood" signal (it was removed). `Weights`/`ScoreBreakdown` are frozen Pydantic models.
- **`rich` is a real core dependency** — the import/enrich pipelines render progress with it.
  Keep it in core deps even though it's UI-flavored.
- **Everything is synchronous** (sync SQLAlchemy + httpx), except the enrichment pipeline which is
  async internally and wrapped by `asyncio.run()` in the service.

## Dependencies

`rich`, `sqlalchemy>=2.0`, `pyyaml`, `httpx`, `numpy`, `pydantic>=2.0`; dev group: `pytest`.
After changing deps: `uv lock && uv sync`
in `core/`, then re-lock dependent apps (`cd ../cli && uv lock`, same for `web/`).

The database is a single SQLite file (`database.path` in config, default
`~/.local/share/musicseed/musicseed.db`). Postgres/pgvector were removed (see
`docs/musicseed-dependency-architecture.html`); `scripts/migrate_pg_to_sqlite.py` migrates an old
Postgres database one-shot.

## Verify (from `core/`)

```bash
uv run ruff check src tests
uv run pytest tests -q                 # offline unit tests (tmp files + mocked Plex HTTP)
python3 -m compileall -q src/musicseed
uv run python -c "import musicseed; from musicseed.services import library, enrichment, recommend, populate, discovery; print('ok')"
```

DB-touching work needs a configured `database.path`; `musicseed-cli init-db` creates the SQLite
file. No server or containers are involved.

## Change guidelines

- Keep `services/` surface-agnostic: no Typer, no `print` for user output, no HTTP framework
  imports. Return result models and raise typed exceptions; let surfaces format and map them.
- Schema changes: prefer additive migrations / `ensure_schema()`-style compatibility for this
  local project unless a real migration system is introduced intentionally.
- Recommendation changes: preserve explainability — update `ScoreBreakdown` and the resolver docs
  when adding or changing a signal.
- If you add a new service, expose it as a function returning a Pydantic model so every surface
  (cli, api, web) can adopt it without reaching into `recommender/`/`db/` directly.
