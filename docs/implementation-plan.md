# MusicSeed Implementation Plan

## Overview

Implementation plan for MusicSeed - a music recommendation CLI tool that creates Plex playlists based on seed tracks, combining sonic similarity (embeddings) with popularity signals.

**Reference:** `/Users/dafevara/Projects/MusicSeed/docs/ard/001-initial-system-design.md`

---

## Target Platform

| Attribute | Specification |
|-----------|---------------|
| **OS** | macOS 15+ (Sequoia) |
| **Architecture** | Apple Silicon (arm64) |
| **Hardware** | Mac Mini M4 / MacBook Pro M1 Pro |
| **Python** | 3.11+ |
| **Package Manager** | uv |

---

## Tech Stack Summary

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Package Manager | uv |
| CLI Framework | Typer + Rich |
| Database | PostgreSQL 16 + pgvector |
| ORM | SQLAlchemy 2.0 |
| HTTP Client | httpx (async) |
| Audio Embeddings | Essentia (MusiCNN) |
| Distribution | Run from source |

---

## Project Structure

```
musicseed/
├── pyproject.toml
├── README.md
├── src/
│   └── musicseed/
│       ├── __init__.py
│       ├── cli.py                 # CLI entry point (Typer)
│       ├── config.py              # Configuration loading
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py          # SQLAlchemy models
│       │   ├── schema.sql         # Raw SQL for reference
│       │   └── session.py         # Database connection
│       ├── importers/
│       │   ├── __init__.py
│       │   └── plex.py            # Plex SQLite importer
│       ├── enrichers/
│       │   ├── __init__.py
│       │   └── spotify.py         # Spotify API client
│       ├── embeddings/
│       │   ├── __init__.py
│       │   ├── essentia_embed.py  # Audio embedding generator
│       │   └── pipeline.py        # Batch embedding pipeline
│       ├── recommender/
│       │   ├── __init__.py
│       │   ├── scoring.py         # Recommendation scoring
│       │   ├── candidates.py      # Multi-signal candidate pool
│       │   └── playlist.py        # Seed resolution + playlist generation
│       └── clients/
│           ├── __init__.py
│           └── plex_api.py        # Plex API client
├── tests/
│   ├── __init__.py
│   ├── test_plex_importer.py
│   ├── test_spotify_enricher.py
│   ├── test_recommender.py
│   └── fixtures/
└── docker-compose.yml             # PostgreSQL + pgvector
```

---

## Implementation Phases

### Phase 1: Foundation (MVP)

**Goal:** Project setup, database, Plex import, basic CLI

#### 1.1 Project Setup
- [ ] Create project with `uv init musicseed`
- [ ] Set up `src/musicseed/` package structure
- [ ] Add dependencies with uv:
  ```bash
  uv add typer rich sqlalchemy "psycopg[binary]" pgvector pyyaml httpx numpy
  ```
- [ ] Create `docker-compose.yml` for PostgreSQL 16 + pgvector
- [ ] Create config file structure (`~/.config/musicseed/config.yaml`)
- [ ] Verify setup: `uv run musicseed --help`

#### 1.2 Database Schema
- [ ] Create SQLAlchemy models in `src/musicseed/db/models.py`:
  - `Artist` (id, name, mbid, spotify_id, plex_id, spotify_popularity)
  - `Album` (id, title, artist_id, year, label, mbid, spotify_id, plex_id)
  - `Track` (id, title, album_id, artist_id, duration_ms, year, file_path, mbid, spotify_id, plex_id, spotify_popularity, embedding, embedding_generated)
  - `Mood`, `Style`, `Genre` (id, name)
  - `TrackMood`, `TrackStyle`, `TrackGenre` (junction tables)
  - `PlayHistory` (id, track_id, played_at, device_id)
  - `TrackStats` (track_id, play_count, last_played_at)
  - `Playlist`, `PlaylistTrack`
- [ ] Create database session management in `src/musicseed/db/session.py`
- [ ] Add Alembic for migrations (optional but recommended)

#### 1.3 Plex Importer
- [ ] Create `src/musicseed/importers/plex.py`:
  - `PlexImporter` class
  - Read Plex SQLite database (read-only mode)
  - Extract artists (metadata_type = 8)
  - Extract albums (metadata_type = 9)
  - Extract tracks (metadata_type = 10)
  - Extract tags by type (1=genre, 300=mood, 301=style, 314=mbid)
  - Extract play history from `metadata_item_views`
  - Extract file paths from `media_parts`
  - Handle parent_id relationships (track → album → artist)
- [ ] Implement incremental import (only new/updated since last import)

#### 1.4 CLI Structure
- [ ] Create `src/musicseed/cli.py` with Typer:
  - `musicseed import` command
  - `musicseed status` command
- [ ] Create config loader in `src/musicseed/config.py`

#### 1.5 Verification
```bash
# Start PostgreSQL
docker-compose up -d

# Run import
uv run musicseed import --plex-db "~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"

# Check status
uv run musicseed status
# Should show: Total tracks (~60K), albums, artists, with moods/styles/genres
```

---

### Phase 2: Metadata Enrichment

**Goal:** Fetch provider metadata and popularity, using ListenBrainz as the primary popularity source and Spotify as an optional fallback.

#### 2.1 ListenBrainz Popularity Client (Async)
- [x] Create `src/musicseed/enrichers/listenbrainz.py`:
  - Batched `POST /1/popularity/recording` lookups by MusicBrainz recording MBID
  - Store raw listen and listener counts
  - Normalize listen counts into provider-neutral `popularity_score`

#### 2.2 Spotify API Client (Async)
- [ ] Create `src/musicseed/enrichers/spotify.py`:
  - `SpotifyClient` class using `httpx.AsyncClient`
  - OAuth client credentials flow
  - Rate limiting (respect 429 responses, exponential backoff)
  - Configurable concurrency (default: 5 concurrent requests)
  - Search endpoint: `GET /search?type=track&q=...`
  - Batch get tracks: `GET /tracks?ids=...` (50 max per request)

#### 2.3 Track Matching
- [ ] Implement search query building:
  - Query: `track:{title} artist:{artist} album:{album}`
  - Normalize strings (remove special chars, lowercase)
- [ ] Implement match scoring:
  - Compare returned results with local metadata
  - Score by title similarity + artist similarity + album similarity
  - Accept match if score > threshold (e.g., 0.8)
- [ ] Store `spotify_id` and `spotify_popularity` on match

#### 2.4 Batch Pipeline
- [ ] Implement batch enrichment with progress tracking
- [ ] Save progress to allow resumption on interrupt
- [ ] Log unmatched tracks for manual review

#### 2.5 CLI Command
- [x] Add `musicseed enrich` command:
  - `--source listenbrainz` for MBID-based popularity enrichment
  - `--source spotify` for Spotify fallback/search enrichment
  - `--batch-size N`
  - `--limit N`
  - `--resume`

#### 2.5 Verification
```bash
uv run musicseed enrich --source listenbrainz --batch-size 100 --limit 1000

uv run musicseed status
# Should show ListenBrainz and Spotify enrichment percentages
```

---

### Phase 3: Audio Embeddings

**Goal:** Generate vector embeddings for all tracks using Essentia MusiCNN

#### 3.1 Essentia Integration
- [ ] Add Essentia to dependencies: `uv add essentia-tensorflow`
- [ ] Create `src/musicseed/embeddings/essentia_embed.py`:
  - `EssentiaEmbedder` class
  - Load MusiCNN model (Apple Silicon native)
  - Process audio file → 200-dim embedding (msd-musicnn-1 feature layer)
  - Handle various audio formats (FLAC, MP3, etc.)

#### 3.2 Batch Pipeline
- [ ] Implement batch embedding with progress tracking
- [ ] Process files in parallel (multiprocessing)
- [ ] Save progress for resumption
- [ ] Handle corrupted/unreadable files gracefully

#### 3.3 pgvector Index
- [ ] Create IVFFlat index after initial embedding generation:
  ```sql
  CREATE INDEX idx_tracks_embedding ON tracks
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
  ```
- [ ] Tune `lists` parameter based on collection size

#### 3.4 CLI Command
- [ ] Add `musicseed embed` command:
  - `--model essentia` (default)
  - `--batch-size N`
  - `--limit N`
  - `--missing-only`

#### 3.5 Verification
```bash
uv run musicseed embed --batch-size 20 --workers 8 --limit 500

uv run musicseed status
# Should show: "With embeddings: X (Y%)"

# Test similarity search (debug query)
uv run musicseed debug similarity --track-id 123 --limit 10
```

---

### Phase 4: Recommendation Engine

**Goal:** Generate playlists from seed tracks

#### 4.1 Seed Resolution
- [ ] Create `src/musicseed/recommender/playlist.py`:
  - Parse seed input: "Artist - Title" or track ID
  - Fuzzy match against database (using trigram similarity or Levenshtein)
  - Return matched track(s) or error if ambiguous

#### 4.2 Scoring Algorithm
- [ ] Create `src/musicseed/recommender/scoring.py`:
  - `Weights` dataclass with defaults
  - `ScoreBreakdown` dataclass for explainable CLI output
  - `calculate_score()` function per ARD section 8.1
  - Popularity proximity: `1 - abs(seed_popularity - candidate_popularity) / 100`
  - Jaccard similarity for mood/style/genre alignment
  - Era proximity calculation
  - Novelty boost from play count

#### 4.3 Candidate Generation and Recommendation Pipeline
- [ ] Create `src/musicseed/recommender/candidates.py`:
  - Sonic candidates from pgvector when embeddings exist
  - Genre, mood, and style candidates from Plex tags
  - Era candidates from nearby release years
  - Popularity candidates from Spotify popularity proximity
  - Novelty candidates from unplayed/lightly played tracks
- [ ] Implement recommendation flow:
  1. Resolve seed tracks
  2. Aggregate seed embedding, tags, year, and popularity
  3. Build a merged candidate pool from all available signal sources
  4. Score and rank candidates with component breakdowns
  5. Apply final selection constraints such as max tracks per artist and year filters
  6. Return top N tracks

#### 4.4 CLI Command
- [ ] Add `musicseed recommend` command:
  - `--seed "Artist - Title"` (repeatable)
  - `--seed-id N`
  - `--limit N`
  - Weight options (`--w-sonic`, `--w-popularity`, `--w-genre`, etc.)
  - `--dry-run` (output to console only, no Plex)
  - `--explain` (show score components for each selected track)

#### 4.5 Verification
```bash
uv run musicseed recommend \
  --seed "Portishead - Wandering Star" \
  --limit 20 \
  --dry-run

# Should output ranked list with scores
```

---

### Phase 5: Plex Playlist Integration

**Goal:** Create playlists directly in Plex

#### 5.1 Plex API Client
- [ ] Create `src/musicseed/clients/plex_api.py`:
  - `PlexClient` class
  - Authentication with Plex token
  - Create playlist: `POST /playlists`
  - Add items to playlist: `PUT /playlists/{id}/items`
  - Get library section ID

#### 5.2 Playlist Creation
- [ ] Map MusicSeed track IDs → Plex `metadata_item_id`
- [ ] Create or update playlist by name
- [ ] Handle errors (track not found, auth failure)

#### 5.3 Full Recommend Command
- [ ] Add `--playlist NAME` option to `recommend` command
- [ ] Store playlist metadata in local DB for reference

#### 5.4 Verification
```bash
uv run musicseed recommend \
  --seed "Massive Attack - Teardrop" \
  --seed "Portishead - Wandering Star" \
  --limit 50 \
  --playlist "Late Night Vibes"

# Open Plexamp → verify playlist exists with correct tracks
```

---

### Phase 6: Polish

**Goal:** Production-ready tool

- [ ] Error handling and user-friendly messages
- [ ] Logging (configurable verbosity)
- [ ] Config validation on startup
- [ ] `--help` documentation for all commands
- [ ] README with setup instructions
- [ ] Performance optimization for large libraries

---

## Key Files to Create

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project dependencies and metadata |
| `docker-compose.yml` | PostgreSQL + pgvector container |
| `src/musicseed/cli.py` | CLI entry point |
| `src/musicseed/config.py` | Configuration loading |
| `src/musicseed/db/models.py` | SQLAlchemy ORM models |
| `src/musicseed/db/session.py` | Database connection management |
| `src/musicseed/importers/plex.py` | Plex SQLite importer |
| `src/musicseed/enrichers/spotify.py` | Spotify API client |
| `src/musicseed/embeddings/essentia_embed.py` | Audio embedding generator |
| `src/musicseed/recommender/scoring.py` | Recommendation scoring |
| `src/musicseed/recommender/playlist.py` | Playlist generation |
| `src/musicseed/clients/plex_api.py` | Plex API client |

---

## Dependencies

```toml
[project]
name = "musicseed"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.9.0",
    "rich>=13.0",
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.1",
    "pgvector>=0.2",
    "pyyaml>=6.0",
    "httpx>=0.25",
    "numpy>=1.24",
    "essentia>=2.1b6",
]

[project.scripts]
musicseed = "musicseed.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/musicseed"]
```

**Note:** Use `uv` for package management:
```bash
# Create project and install dependencies
uv init musicseed
cd musicseed
uv add typer rich sqlalchemy "psycopg[binary]" pgvector pyyaml httpx numpy essentia
```

---

## Verification Checklist

After each phase, verify:

1. **Phase 1:** `musicseed status` shows correct counts from Plex
2. **Phase 2:** `musicseed status` shows Spotify match percentage
3. **Phase 3:** `musicseed status` shows embedding percentage; similarity search returns sensible results
4. **Phase 4:** `musicseed recommend --dry-run` outputs ranked track list
5. **Phase 5:** Playlist appears in Plexamp with correct tracks
6. **Phase 6:** Tool handles errors gracefully, logs are useful

---

## Resolved Decisions

| Decision | Resolution |
|----------|------------|
| Project location | `/Users/dafevara/Projects/MusicSeed/` |
| Target platform | macOS Apple Silicon (M1 Pro → M4 Mac Mini) |
| Distribution | Run from source (`uv run musicseed`) |
| Embedding model | Essentia MusiCNN |
| Spotify concurrency | Async with httpx |
| Database | PostgreSQL 16 + pgvector |

## Prerequisites (User Action Required)

1. **Spotify API credentials**: Create app at https://developer.spotify.com/dashboard
2. **Plex token**: Obtain from Plex settings or via https://plex.tv/api/resources
3. **PostgreSQL**: Install via Docker or Homebrew
4. **Plex database path**: `~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db`
