# MusicSeed — Dependency Reduction Plan

**Goal:** Remove Essentia self-embedding generation, use Plex sonic vectors as the only sonic
signal, replace PostgreSQL + pgvector with SQLite, and eliminate the Docker/docker-compose
requirement entirely.

**Status:** Implemented (August 2026). All four phases are complete: Essentia removed, sonic
vectors read at query time (ARD 002 superseded the "store 50-dim JSON" variant of Phase 2 —
no vectors are stored at all), PostgreSQL/pgvector/Docker replaced by a single SQLite file
(`~/.local/share/musicseed/musicseed.db`), and docs updated. Existing Postgres data was
migrated with `scripts/migrate_pg_to_sqlite.py` (all 13 tables, exact row counts); a pg_dump
backup was kept at `musicseed-pg-backup-*.dump` in the repo root.

---

## 1. Rationale (validated against the code)

### Essentia was an experiment that lost
- Self-generated embeddings (MusiCNN via `essentia-tensorflow==2.1b6.dev1389`) are dropped.
- Plex's own sonic analysis vectors — already imported from the Plex blobs DB via
  `import-plex-sonic` — become the **only** sonic signal.

### pgvector was load-bearing only for embeddings
- pgvector is used in **exactly one query**: the sonic candidate query in
  `core/src/musicseed/recommender/candidates.py` (`cosine_distance` ORDER BY + IVFFlat index).
- Scoring-side cosine similarity (`recommender/scoring.py`) is already **pure numpy** — it does
  not touch the database vector operators.
- `pg_trgm` is created in `optimize-db` but **never used in any query** — dead weight.

### The 200-dim shape is an essentia artifact
- Plex sonic vectors are natively **50-dim** (`PLEX_SONIC_DIM = 50` in `importers/plex.py`).
- `_decode_plex_sonic_vector()` zero-pads them to 200 only to share the `Vector(200)` column
  with MusiCNN embeddings. Remove essentia → store native 50-dim → delete the padding hack.

### The scale makes brute-force search trivially safe
- ~60K tracks × 50 float32 dims ≈ 12 MB.
- A numpy matmul for "top-N nearest to seed" is single-digit **milliseconds** — faster than a
  round-trip to a Postgres server. IVFFlat solves a problem this project doesn't have.

### Postgres-dialect usage is minimal
Only three column types need equivalents:

| Postgres type | Where | SQLite replacement |
|---|---|---|
| `UUID` | `mbid` on Artist/Album/Track | `String(36)` |
| `ARRAY(Integer)` | `Playlist.seed_track_ids` | `JSON` |
| `JSONB` | `Playlist.weights` | `JSON` |

### Biggest hidden win: no more audio-file access
Dropping `embed` deletes the **path-identity problem** — MusicSeed stops reading music files
entirely (that was only needed to generate embeddings). The remaining dependency graph:

- Plex metadata DB (read-only SQLite)
- Plex blobs DB (read-only SQLite, sonic vectors)
- Plex HTTP API (playlists, sonic triggers)
- One local SQLite file (MusicSeed's own state)
- External APIs (ListenBrainz / MusicBrainz / Spotify)

---

## 2. Phase 1 — Remove self-embedding generation

- Delete `core/src/musicseed/embeddings/` (`pipeline.py`, `essentia_embed.py`, `__init__.py`).
- Remove `services/enrichment.generate_embeddings` (keep `enrich_tracks`).
- Remove the CLI `embed` command module + its registration in `commands/__init__.py`.
- Remove `EmbeddingConfig` from `core/src/musicseed/config.py` (and any config.yaml examples).
- Drop `essentia-tensorflow` from `core/pyproject.toml`. **Keep `numpy`** — scoring uses it.
- Core deps go from 10 → 6: `sqlalchemy, psycopg→(removed in P3), pgvector→(removed in P3),
  httpx, numpy, pydantic, pyyaml, rich`.

## 3. Phase 2 — De-pgvector the data model

- `Track.embedding`: `Vector(200)` → **JSON column holding the native 50-dim vector**
  (simple, debuggable; at 50 dims the perf difference vs BLOB is irrelevant).
- Keep `embedding_model` (e.g. `"plex-sonic-v7"`) as the guard that vectors are comparable.
- `embedding_generated` flag: keep or fold into `embedding IS NOT NULL` — decide during
  implementation.
- Remove zero-padding in `_decode_plex_sonic_vector()`; store the 50 values as-is.
- Rewrite the sonic branch of `build_candidate_pool()`:
  - Load `(id, embedding)` for tracks with `embedding_model == seed.embedding_model`.
  - One numpy matmul of candidate matrix × seed vector → cosine distances → top-N.
  - Same `CandidatePool` interface; no DB vector operators.
- `scoring.py` cosine path works unchanged (already numpy).

## 4. Phase 3 — PostgreSQL → SQLite

### Model changes (`db/models.py`)
- `UUID(as_uuid=False)` → `String(36)` (3 `mbid` columns).
- `ARRAY(Integer)` → `JSON` (`Playlist.seed_track_ids`).
- `JSONB` → `JSON` (`Playlist.weights`).
- Remove `from pgvector.sqlalchemy import Vector` and
  `from sqlalchemy.dialects.postgresql import …`.

### Config (`config.py`)
- `DatabaseConfig {host, port, name, user, password}` → single `path`,
  default `~/.local/share/musicseed/musicseed.db` (env/`~` expansion already exists).
- `url` property → `sqlite:///{path}`.

### Engine/session (`db/session.py`)
- SQLite engine with WAL mode pragma (`PRAGMA journal_mode=WAL`) and `foreign_keys=ON`.
- Delete `CREATE EXTENSION vector` / `pg_trgm`.
- `create_indexes()`: drop IVFFlat + trigram entries; keep plain b-tree indexes
  (artist, album, plex_id, spotify_id, etc.).
- `ensure_schema()`: drop the `vector(512) → vector(200)` ALTER branch; keep the additive
  pattern for future columns.
- `init_db()`: plain `create_all` + ensure parent dir of the DB file exists.

### CLI
- `init-db` / `optimize-db` / `status`: adapt messaging (no server, file path shown).
- Remove Postgres connection troubleshooting output; show DB file size instead.

### Packaging / repo
- Drop `psycopg[binary]` and `pgvector` from `core/pyproject.toml`.
- Delete root `docker-compose.yml`.
- After dep changes: `uv lock && uv sync` in `core/`, then `cd ../cli && uv lock`.

### Data migration (existing Postgres → SQLite)
- Enrichment rows cost real ListenBrainz/Spotify API calls, so provide a **one-shot migration
  script** (e.g. `scripts/migrate_pg_to_sqlite.py`) that:
  1. Creates the SQLite schema.
  2. Streams every table from Postgres, converting `Vector` → JSON list (and un-padding
     200→50 where the model is `plex-sonic-v7`), `UUID` → str, `ARRAY`/`JSONB` → JSON.
  3. Reports per-table row counts.
- **Open decision:** migrate existing data vs. start fresh and re-run import/enrichment.

## 5. Phase 4 — Docs

- Update `AGENTS.md` (root), `core/AGENTS.md`, `cli/AGENTS.md`:
  - dependency lists, verify commands (no `docker-compose up -d`), `embed` command removal,
    sonic-import-only embedding story, DB file location.
- Update `docs/infra/local-runtime.md` (no Docker; SQLite file ops; backup = copy one file).
- Update `docs/resolvers/recommendation-resolvers.md` if the sonic candidate mechanics change
  is user-visible (it isn't — same signal, different retrieval).
- Regenerate/update `/tmp/musicseed-dependency-architecture.html` explainer after the change.
- README (for open source): install becomes `pip install` + point at Plex — no Docker section.

---

## 6. Resulting dependency & runtime footprint

**Before:** Python 3.11 + Docker + Postgres 16 + pgvector + essentia-tensorflow (+TensorFlow
runtime) + psycopg + audio-file access.

**After:** Python 3.11 + 6 core deps (`sqlalchemy, httpx, numpy, pydantic, pyyaml, rich`)
+ Typer CLI. One SQLite file. No server, no containers, no native ML libs, no audio reads.

**Consequences:**
- ARM NAS / Raspberry Pi works out of the box (essentia was amd64-only).
- Backup story: copy one file.
- Install for hi-fi enthusiasts: `pip install` (or `uv tool install`) + config.yaml.

## 7. Trade-offs accepted

- Sonic candidate search becomes a full in-memory scan per query — fine up to hundreds of
  thousands of tracks; a known non-problem at personal-library scale.
- SQLite is single-writer — fine for a single-user CLI; the future `api/` surface must keep
  writes serialized (it already would be, single process).
- Postgres stays theoretically reachable via SQLAlchemy URL override, but the project will not
  test/maintain that path — SQLite is the supported database.

## 8. Verification checklist (post-implementation)

```bash
cd core && uv run ruff check src
python3 -m compileall -q core/src/musicseed cli/src/musicseed
cd cli && uv run musicseed --help                       # no `embed` command
uv run musicseed init-db                                # creates SQLite file
uv run musicseed import                                 # from Plex DB (ro)
uv run musicseed import-plex-sonic                      # 50-dim vectors, no padding
uv run musicseed recommend --seed-id 123 --limit 20 --explain
uv run musicseed status
```

Plus: run the pg→sqlite migration script against a copy of the real Postgres DB and diff
row counts per table; spot-check `tracks.embedding` length = 50.
