# musicseed-core — Agent Guide

`core/` is the reusable library that holds **all** of MusicSeed's logic: Plex import, metadata
enrichment, audio embeddings, the recommender, database access, and configuration. It has no
user interface. Every app surface (the `cli/`, and future `api/`/`mcp/`) depends on this package
and drives it through the `services/` layer.

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
  `import_plex_sonic`, `get_status`.
- `services/enrichment.py`: `enrich_tracks` (**calls `asyncio.run()` internally — never call it
  from inside a running event loop; offload to a thread**), `generate_embeddings`.
- `services/recommend.py`: `get_recommendations`, `create_playlist`.
- `services/populate.py`: `list_plex_playlists`, `get_populate_recommendations`,
  `populate_playlist`.
- `services/plex_analysis.py`: `get_sonic_status`, `probe_sonic_trigger`,
  `probe_butler_trigger`, `refresh_album`, `refresh_sonic_analysis` — inspect Plex sonic
  analysis coverage over the HTTP API (`musicAnalysisVersion`) and trigger it on demand via
  `POST /butler/MusicAnalysis` (proven to work; per-item `analyze` does NOT trigger sonic
  analysis). The Butler task always processes Plex's whole pending backlog; date windows only
  scope watching/reporting.

## Code Map

- `config.py`: Pydantic YAML config + `${ENV}`/`~` expansion. `get_config()`/`set_config()`/
  `load_config()` global singleton. This is the CLI's config mechanism; future apps may populate
  the same `Config` from `.env` instead.
- `exceptions.py`: `MusicSeedError` (base), `ConfigurationError`, `NotFoundError`.
- `logging_config.py`: `setup_logging`/`get_logger`. **Gotcha:** `setup_logging` walks up from its
  own `__file__` to the nearest `pyproject.toml` and writes `logs/` beside it, so logs land in
  `core/logs/`. Pass an explicit `log_dir` to override.
- `db/models.py`: SQLAlchemy 2.0 ORM (Artist, Album, Track, tag tables, play history, stats,
  playlists). `Track.embedding` is a `pgvector` `Vector(200)`.
- `db/session.py`: `get_engine`, `get_session_factory` (`expire_on_commit=False`), `get_session`
  (commit/rollback/close context manager), `init_db`, `ensure_schema` (additive migrations),
  `create_indexes`, `reset_engine` (dispose engine — the hook for tests/config reload).
- `importers/plex.py`: Plex SQLite metadata + sonic-blob import.
- `enrichers/`: ListenBrainz, Spotify, MusicBrainz clients + the async enrichment pipeline.
- `embeddings/`: Essentia audio-embedding pipeline and model wrapper.
- `recommender/`: `scoring.py` (`Weights`, `ScoreBreakdown`, `SeedProfile`, `calculate_score`),
  `candidates.py` (`build_candidate_pool`), `playlist.py` (`Recommendation`, `recommend_tracks`,
  `resolve_seed_tracks` — raises `ValueError` on unresolved seeds), `populate.py`
  (`PopulateMethod = "average" | "frequency"`, `populate_playlist_recommendations`).
- `clients/plex_api.py`: thin synchronous Plex HTTP client (httpx). Raises `PlexAPIError`.

## Particularities to respect

- **Result models embed raw ORM objects.** `Recommendation`, `RecommendationResult`, etc. use
  `model_config = {"arbitrary_types_allowed": True}` and hold live SQLAlchemy `Track` objects, so
  they are **not directly JSON-serializable**. A JSON surface (the future `api/`) must project
  `Track` into DTOs. Sessions use `expire_on_commit=False` and eager `selectinload`, so returned
  `Track`s stay usable after the session closes — preserve both if you touch loading.
- **Recommendation signals are exactly six**: sonic, popularity, style, genre, era, novelty. There
  is no "mood" signal (it was removed). `Weights`/`ScoreBreakdown` are frozen Pydantic models.
- **`rich` is a real core dependency** — the import/enrich/embed pipelines render progress with it.
  Keep it in core deps even though it's UI-flavored.
- **`essentia-tensorflow` is pinned to `==2.1b6.dev1389`.** Newer dev builds dropped CPython 3.11
  wheels; do not loosen this pin without confirming a cp311 wheel exists.
- **Everything is synchronous** (sync SQLAlchemy + httpx), except the enrichment pipeline which is
  async internally and wrapped by `asyncio.run()` in the service.

## Dependencies

`rich`, `sqlalchemy>=2.0`, `psycopg[binary]`, `pgvector`, `pyyaml`, `httpx`, `numpy`,
`essentia-tensorflow==2.1b6.dev1389`, `pydantic>=2.0`. After changing deps: `uv lock && uv sync`
in `core/`, then re-lock dependent apps (`cd ../cli && uv lock`).

## Verify (from `core/`)

```bash
uv run ruff check src
python3 -m compileall -q src/musicseed
uv run python -c "import musicseed; from musicseed.services import library, enrichment, recommend, populate; print('ok')"
```

DB-touching work needs `docker-compose up -d` (from the repo root) and a configured database.

## Change guidelines

- Keep `services/` surface-agnostic: no Typer, no `print` for user output, no HTTP framework
  imports. Return result models and raise typed exceptions; let surfaces format and map them.
- Schema changes: prefer additive migrations / `ensure_schema()`-style compatibility for this
  local project unless a real migration system is introduced intentionally.
- Recommendation changes: preserve explainability — update `ScoreBreakdown` and the resolver docs
  when adding or changing a signal.
- If you add a new service, expose it as a function returning a Pydantic model so the CLI (and
  future API) can adopt it without reaching into `recommender/`/`db/` directly.
