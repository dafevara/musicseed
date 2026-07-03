# musicseed-core

Core library for [MusicSeed](../README.md). It contains all of the project's logic — Plex import,
metadata enrichment, audio embeddings, the recommender, database access, and configuration — with
**no user interface**. App surfaces such as [`../cli`](../cli) depend on this package and drive it
through its `services/` layer.

- Distribution: `musicseed-core` · Import package: `musicseed`
- This is a library: no console command is installed from here.

## Using it as a dependency

Sibling apps declare an editable path dependency (see `cli/pyproject.toml`):

```toml
[project]
dependencies = ["musicseed-core", ...]

[tool.uv.sources]
musicseed-core = { path = "../core", editable = true }
```

Then call the surface-agnostic services, which manage their own DB session and return Pydantic
result models:

```python
from musicseed.services import recommend
from musicseed.recommender.scoring import Weights

result = recommend.get_recommendations(seed_ids=[123], limit=20, weights=Weights())
for rec in result.recommendations:
    print(rec.track.title, rec.score.total)
```

Note: result models wrap live SQLAlchemy `Track` objects (`arbitrary_types_allowed=True`), so they
are not directly JSON-serializable — a JSON surface must project them into DTOs.

## Layout

```
core/
├── pyproject.toml            # musicseed-core; deps; hatchling build of src/musicseed
├── uv.lock
└── src/musicseed/
    ├── config.py  exceptions.py  logging_config.py
    ├── db/                    # SQLAlchemy models + session/engine/schema/indexes
    ├── services/             # surface-agnostic application layer (call this)
    ├── recommender/          # seed resolution, candidates, scoring, playlist/populate
    ├── enrichers/            # ListenBrainz / Spotify / MusicBrainz + pipeline
    ├── embeddings/           # Essentia audio-embedding pipeline
    ├── importers/            # Plex SQLite metadata + sonic import
    └── clients/plex_api.py   # Plex Media Server HTTP client
```

## Develop (from `core/`)

```bash
uv sync
uv run ruff check src
python3 -m compileall -q src/musicseed
```

`essentia-tensorflow` is pinned to `2.1b6.dev1389` (newer dev builds drop CPython 3.11 wheels).
DB-touching work needs `docker-compose up -d` from the repo root and a configured database.

See [`AGENTS.md`](AGENTS.md) for the full code map, service entry points, and conventions.
