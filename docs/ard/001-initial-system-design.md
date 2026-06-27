# MusicSeed - Product Requirements Document

## System Design for Music Recommendation Engine

**Version:** 1.1
**Date:** January 2025
**Status:** Final Draft

---

## 1. Overview

### 1.1 Problem Statement

Plex Media Server with Plexamp provides excellent music playback and basic sonic analysis, but its recommendation and discovery capabilities are limited to a single dimension (acoustic similarity). Music fans with large collections (4TB+) need multi-dimensional discovery that combines:

- Sonic/acoustic similarity
- Popularity signals
- Mood and style alignment
- Personal listening history
- Temporal preferences

### 1.2 Solution

MusicSeed is a companion tool that:

1. Enriches an existing Plex music library with external metadata (Spotify popularity, MusicBrainz IDs)
2. Generates audio embeddings for sonic similarity matching
3. Provides a CLI for creating Plex playlists based on seed tracks with configurable recommendation weights

### 1.3 Target User

Self-hosting music enthusiasts with:
- A running Plex Media Server with music library
- Technical comfort with CLI tools and Python
- Desire for better music discovery within their existing collection

### 1.4 Collection Profile

- **Size:** ~60,000 audio files
- **Storage:** 2-3TB (primarily FLAC, high-quality)
- **Existing metadata:** Plex-enriched with moods, styles, genres, MusicBrainz IDs (~53K tracks with MBIDs)

---

## 2. Goals and Non-Goals

### 2.1 Goals

- **G1:** Extract and leverage existing Plex metadata (tags, MBIDs, play history, mood/style)
- **G2:** Enrich library with ListenBrainz popularity data, using Spotify as optional fallback
- **G3:** Generate audio embeddings for sonic similarity search
- **G4:** Provide seed-based playlist generation with soft-weighted ranking
- **G5:** Create playlists directly in Plex via API
- **G6:** Single PostgreSQL database with pgvector (operational simplicity)

### 2.2 Non-Goals (v1)

- Full Plex/Plexamp replacement
- Web UI or mobile app
- Real-time streaming or playback
- Social features or multi-user support
- Discogs/MusicBrainz/Last.fm popularity (deferred)
- Neo4j or graph-based recommendations
- Windows or Linux support (macOS only for v1)
- Packaged binary distribution (run from source only)

---

## 3. User Stories

### 3.1 Primary Use Case

> As a music fan, I want to select one or more seed tracks and generate a playlist of similar tracks from my collection, ranked by sonic similarity and popularity, so I can discover music that matches a vibe.

### 3.2 Supporting Use Cases

| ID | Story |
|----|-------|
| US-1 | As a user, I want to import my Plex library metadata into MusicSeed |
| US-2 | As a user, I want MusicSeed to enrich my tracks with Spotify popularity |
| US-3 | As a user, I want to generate audio embeddings for my FLAC files |
| US-4 | As a user, I want to create a playlist from seed tracks with configurable weights |
| US-5 | As a user, I want the playlist to appear in Plexamp automatically |
| US-6 | As a user, I want to boost unplayed tracks to discover hidden gems |
| US-7 | As a user, I want to prefer tracks from a specific era/decade |
| US-8 | As a user, I want artist diversity (avoid 10 tracks from same artist) |

---

## 4. System Architecture

### 4.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              MusicSeed                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   CLI       │───▶│  Core       │───▶│  Plex API   │                 │
│  │   (Typer)   │    │  Engine     │    │  Client     │                 │
│  └─────────────┘    └──────┬──────┘    └─────────────┘                 │
│                            │                                            │
│                            ▼                                            │
│                     ┌─────────────┐                                     │
│                     │ PostgreSQL  │                                     │
│                     │ + pgvector  │                                     │
│                     └─────────────┘                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
         │                    │                       │
         ▼                    ▼                       ▼
┌─────────────┐      ┌─────────────┐         ┌─────────────┐
│ Plex SQLite │      │ Spotify API │         │ FLAC Files  │
│ (read-only) │      │   (async)   │         │ (~60K)      │
└─────────────┘      └─────────────┘         └─────────────┘
```

### 4.2 Component Overview

| Component | Responsibility |
|-----------|----------------|
| **CLI Interface** | User commands, argument parsing, output formatting (Typer + Rich) |
| **Core Engine** | Recommendation logic, scoring, playlist generation |
| **Plex Importer** | Read Plex SQLite DB, extract metadata/tags/history |
| **ListenBrainz Enricher** | Fetch recording listen/user counts by MusicBrainz ID (async httpx) |
| **Spotify Enricher** | Optional fallback to match tracks to Spotify and fetch popularity (async httpx) |
| **Embedding Generator** | Process FLAC files, generate audio embeddings (Essentia MusiCNN) |
| **Plex API Client** | Create/manage playlists in Plex server |
| **PostgreSQL + pgvector** | Store all data, vector similarity search |

---

## 5. Data Flow

### 5.1 Initial Setup Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INITIAL SETUP                                   │
└─────────────────────────────────────────────────────────────────────────┘

Step 1: PLEX IMPORT
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Plex SQLite │────▶│ Plex        │────▶│ PostgreSQL  │
│             │     │ Importer    │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
     Extracts:             │
     - metadata_items      │
     - tags (mood, style, genre, MBID)
     - metadata_item_views (play history)
     - media_parts (file paths)

Step 2: LISTENBRAINZ / SPOTIFY ENRICHMENT (async)
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ PostgreSQL  │────▶│ Spotify     │────▶│ PostgreSQL  │
│ (tracks)    │     │ Enricher    │     │ (+ spotify) │
└─────────────┘     │ (async)     │     └─────────────┘
                    └─────────────┘
                           │
     For each track:       │
     - Prefer ListenBrainz lookup by MusicBrainz recording MBID
     - Store listen count and unique listener count
     - Normalize ListenBrainz counts into popularity_score
     - Optionally fallback to Spotify search/popularity

Step 3: EMBEDDING GENERATION
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ FLAC Files  │────▶│ Essentia    │────▶│ PostgreSQL  │
│ (~60K)      │     │ MusiCNN     │     │ (+ vectors) │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
     For each file:        │
     - Load audio (FLAC/MP3/etc.)
     - Run through MusiCNN model
     - Store vector(512) in pgvector
```

### 5.2 Recommendation Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      RECOMMENDATION FLOW                                │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────┐
│ CLI Command │
│ --seed X    │
│ --seed Y    │
│ --limit 50  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. RESOLVE SEEDS                                                        │
│    - Parse seed track identifiers (title, ID, or fuzzy match)          │
│    - Fetch seed track embeddings from PostgreSQL                        │
│    - Compute centroid embedding if multiple seeds                       │
└─────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. MULTI-SIGNAL CANDIDATE RETRIEVAL                                     │
│    Build overlapping candidate pools instead of relying on one source:  │
│    - Sonic neighbors from pgvector, when embeddings exist               │
│    - Tracks sharing seed genres, moods, and styles                      │
│    - Tracks from nearby release years                                   │
│    - Tracks with similar Spotify popularity                             │
│    - Underplayed tracks for discovery/novelty                           │
│    Candidate pool size should exceed the requested playlist length      │
│    enough to allow re-ranking and diversity constraints.                │
└─────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. SCORING & RANKING                                                    │
│    For each candidate:                                                  │
│    score = (                                                            │
│        sonic_similarity    * w1 +  # 1 - cosine_distance               │
│        popularity_proximity * w2 + # 1 - |seed_pop - track_pop| / 100  │
│        mood_alignment       * w3 + # jaccard(seed_moods, track_moods)  │
│        style_alignment      * w4 + # jaccard(seed_styles, track_styles)│
│        genre_alignment      * w5 + # jaccard(seed_genres, track_genres)│
│        era_proximity        * w6 + # 1 - |seed_year - track_year|/50   │
│        novelty_boost        * w7   # 1 if never played, else decay     │
│    )                                                                    │
└─────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. PLAYLIST GENERATION                                                  │
│    - Sort by score descending                                          │
│    - Apply constraints: max tracks per artist, exclude seeds, years    │
│    - Take top `limit` tracks                                           │
└─────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. PLEX PLAYLIST CREATION                                               │
│    - Authenticate with Plex API                                        │
│    - Create or update playlist with name                               │
│    - Add tracks by Plex metadata_item_id                               │
└─────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│ Playlist in │
│ Plexamp ✓   │
└─────────────┘
```

---

## 6. Target Platform & Hardware

### 6.1 Development & Deployment Environment

| Attribute | Specification |
|-----------|---------------|
| **Operating System** | macOS 15+ (Sequoia) |
| **Architecture** | Apple Silicon (arm64) |
| **Hardware** | Mac Mini M4 (primary), MacBook Pro M1 Pro (secondary) |
| **RAM** | 16-32GB unified memory |
| **Storage** | Fast SSD for audio file access |

### 6.2 Platform Considerations

- **Apple Silicon native**: All dependencies must have arm64 wheels or build cleanly
- **No Windows support**: Not a requirement for v1
- **No Linux support**: Not a requirement for v1 (could be added later)
- **Plex co-located**: Plex Media Server runs on the same machine or local network

### 6.3 ML/Audio Processing

- **Essentia**: Native Apple Silicon support confirmed
- **GPU acceleration**: Apple Metal/MPS available if needed (not required for v1)
- **Memory**: 16GB sufficient for batch processing with reasonable batch sizes

---

## 7. Database Schema

### 6.1 PostgreSQL with pgvector

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- CORE ENTITIES
-- ============================================

CREATE TABLE artists (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(500) NOT NULL,
    name_sort       VARCHAR(500),

    -- External IDs
    mbid            UUID,
    spotify_id      VARCHAR(50),

    -- Popularity
    spotify_popularity      SMALLINT,  -- 0-100
    spotify_followers       INTEGER,

    -- Plex reference
    plex_guid       VARCHAR(255),
    plex_id         INTEGER,

    -- Timestamps
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE albums (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    title_sort      VARCHAR(500),
    artist_id       INTEGER REFERENCES artists(id),

    -- Metadata
    year            SMALLINT,
    label           VARCHAR(255),

    -- External IDs
    mbid            UUID,
    spotify_id      VARCHAR(50),
    discogs_id      INTEGER,  -- for future use

    -- Plex reference
    plex_guid       VARCHAR(255),
    plex_id         INTEGER,

    -- Timestamps
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE tracks (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(500) NOT NULL,
    title_sort      VARCHAR(500),
    album_id        INTEGER REFERENCES albums(id),
    artist_id       INTEGER REFERENCES artists(id),

    -- Metadata
    duration_ms     INTEGER,
    track_number    SMALLINT,
    disc_number     SMALLINT,
    year            SMALLINT,

    -- File info
    file_path       TEXT,
    file_hash       VARCHAR(64),

    -- External IDs
    mbid            UUID,
    spotify_id      VARCHAR(50),

    -- Popularity (Spotify)
    spotify_popularity      SMALLINT,  -- 0-100
    popularity_score        REAL,      -- normalized 0-1

    -- Embedding (pgvector)
    embedding       vector(512),
    embedding_model VARCHAR(50),  -- 'essentia-musicnn'

    -- Plex reference
    plex_guid       VARCHAR(255),
    plex_id         INTEGER,

    -- Enrichment status
    spotify_matched     BOOLEAN DEFAULT FALSE,
    embedding_generated BOOLEAN DEFAULT FALSE,
    match_tier          SMALLINT,  -- 1=Plex MBID, 2=Spotify search, 3=AcoustID, 4=fuzzy

    -- Timestamps
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- TAGS (from Plex)
-- ============================================

CREATE TABLE moods (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE styles (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE genres (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE track_moods (
    track_id    INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
    mood_id     INTEGER REFERENCES moods(id) ON DELETE CASCADE,
    PRIMARY KEY (track_id, mood_id)
);

CREATE TABLE track_styles (
    track_id    INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
    style_id    INTEGER REFERENCES styles(id) ON DELETE CASCADE,
    PRIMARY KEY (track_id, style_id)
);

CREATE TABLE track_genres (
    track_id    INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
    genre_id    INTEGER REFERENCES genres(id) ON DELETE CASCADE,
    PRIMARY KEY (track_id, genre_id)
);

-- ============================================
-- PLAY HISTORY (from Plex)
-- ============================================

CREATE TABLE play_history (
    id          SERIAL PRIMARY KEY,
    track_id    INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
    played_at   TIMESTAMP NOT NULL,
    device_id   INTEGER,

    -- Plex reference
    plex_view_id INTEGER
);

-- Aggregated stats for faster queries
CREATE TABLE track_stats (
    track_id        INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    play_count      INTEGER DEFAULT 0,
    last_played_at  TIMESTAMP,
    skip_count      INTEGER DEFAULT 0
);

-- ============================================
-- PLAYLISTS
-- ============================================

CREATE TABLE playlists (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,

    -- Generation parameters (for reproducibility)
    seed_track_ids  INTEGER[],
    weights         JSONB,

    -- Plex reference
    plex_playlist_id INTEGER,
    plex_guid        VARCHAR(255),

    -- Timestamps
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE playlist_tracks (
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    track_id    INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
    position    SMALLINT NOT NULL,
    score       REAL,  -- recommendation score at generation time
    PRIMARY KEY (playlist_id, track_id)
);

-- ============================================
-- INDEXES
-- ============================================

-- Vector similarity search
CREATE INDEX idx_tracks_embedding ON tracks
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Common queries
CREATE INDEX idx_tracks_artist ON tracks(artist_id);
CREATE INDEX idx_tracks_album ON tracks(album_id);
CREATE INDEX idx_tracks_plex_id ON tracks(plex_id);
CREATE INDEX idx_tracks_spotify_id ON tracks(spotify_id);
CREATE INDEX idx_tracks_mbid ON tracks(mbid);
CREATE INDEX idx_tracks_popularity ON tracks(popularity_score DESC);
CREATE INDEX idx_tracks_year ON tracks(year);

CREATE INDEX idx_artists_spotify_id ON artists(spotify_id);
CREATE INDEX idx_artists_mbid ON artists(mbid);
CREATE INDEX idx_artists_plex_id ON artists(plex_id);

CREATE INDEX idx_albums_spotify_id ON albums(spotify_id);
CREATE INDEX idx_albums_plex_id ON albums(plex_id);

CREATE INDEX idx_play_history_track ON play_history(track_id);
CREATE INDEX idx_play_history_played_at ON play_history(played_at DESC);
```

---

## 8. Track Matching Strategy

### 7.1 Three-Tier Approach

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    TRACK MATCHING PIPELINE                              │
└─────────────────────────────────────────────────────────────────────────┘

TIER 1: PLEX MUSICBRAINZ IDs
─────────────────────────────
Source: Plex tags table (tag_type = 314)
Format: mbid://xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Coverage: ~53,000+ tracks already matched

    Plex tags (314) ──▶ Extract MBID ──▶ Store in tracks.mbid
                              │
                              ▼
                       MusicBrainz API
                              │
                       Fetch: spotify_id (if linked)
                              artist MBID
                              release MBID


TIER 2: PLEX-MATCHED, NO MBID
─────────────────────────────
Source: Tracks with guid = plex://... but no MBID tag
Approach: Spotify Search API

    Track metadata ──▶ Spotify Search ──▶ Match & Store
    (artist + title      (fuzzy match)     spotify_id
     + album)                              popularity


TIER 3: UNMATCHED (local://)
────────────────────────────
Source: Tracks with guid = local://...
Approach: AcoustID fingerprint → MusicBrainz → Spotify

    FLAC file ──▶ Chromaprint ──▶ AcoustID API ──▶ MBID
                  fingerprint         │
                                      ▼
                               MusicBrainz API
                                      │
                                      ▼
                               Spotify Search
                                      │
                                      ▼
                               Store IDs & popularity

    Fallback: Fuzzy metadata search if fingerprint fails
```

### 8.2 Matching Confidence

| Tier | Source | Confidence | match_tier value |
|------|--------|------------|------------------|
| 1 | Plex MBID tag | High | 1 |
| 2 | Spotify search match | Medium | 2 |
| 3 | AcoustID fingerprint | High | 3 |
| 4 | Fuzzy metadata match | Low | 4 |
| — | Unmatched | — | NULL |

---

## 9. Recommendation Algorithm

### 8.1 Candidate Generation and Scoring

MusicSeed should not treat sonic similarity as the only candidate source. Plex already provides
sonic-only recommendations, and that is not enough for the target use case. The recommendation
engine uses multiple candidate generators, merges their results, then scores the unified candidate
pool.

Candidate generators:

- **Sonic candidates:** nearest neighbors from pgvector when embeddings exist
- **Genre candidates:** tracks sharing seed genres
- **Mood candidates:** tracks sharing seed moods
- **Style candidates:** tracks sharing seed styles
- **Era candidates:** tracks close to the seed release year or average seed year
- **Popularity candidates:** tracks close to the seed Spotify popularity, not merely popular tracks
- **Novelty candidates:** unplayed or lightly played tracks from the user's library

The scoring layer normalizes every signal to `[0, 1]`. Popularity is modeled as proximity to the
seed's popularity level. Absolute popularity can be added later as a separate optional preset, but it
is not the default behavior.

```python
def calculate_score(
    candidate: Track,
    seed_embedding: np.ndarray | None,
    seed_moods: set[str],
    seed_styles: set[str],
    seed_genres: set[str],
    seed_year: int | None,
    seed_popularity: float | None,
    weights: Weights,
) -> ScoreBreakdown:
    """
    Calculate recommendation score for a candidate track.
    All component scores are normalized to [0, 1].
    """

    sonic_sim = cosine_similarity(candidate.embedding, seed_embedding) if seed_embedding else 0.5

    # Popularity proximity, not absolute popularity boost.
    if seed_popularity is not None and candidate.spotify_popularity is not None:
        popularity = 1 - abs(seed_popularity - candidate.spotify_popularity) / 100
    else:
        popularity = 0.5

    mood_alignment = jaccard(seed_moods, set(candidate.moods)) if seed_moods else 0.5
    style_alignment = jaccard(seed_styles, set(candidate.styles)) if seed_styles else 0.5
    genre_alignment = jaccard(seed_genres, set(candidate.genres)) if seed_genres else 0.5

    if seed_year and candidate.year:
        era_proximity = max(0, 1 - abs(seed_year - candidate.year) / 50)
    else:
        era_proximity = 0.5

    play_count = candidate.play_count or 0
    novelty = 1 / (1 + play_count * 0.2)

    score = (
        sonic_sim       * weights.sonic +
        popularity      * weights.popularity +
        mood_alignment  * weights.mood +
        style_alignment * weights.style +
        genre_alignment * weights.genre +
        era_proximity   * weights.era +
        novelty         * weights.novelty
    )

    return ScoreBreakdown(score, sonic_sim, popularity, mood_alignment,
                          style_alignment, genre_alignment, era_proximity, novelty)
```

Artist diversity is applied as a final selection constraint, not as a score component. This keeps
track relevance scoring separate from playlist composition rules.

### 8.2 Default Weights

```python
@dataclass
class Weights:
    sonic: float = 0.30       # Acoustic similarity
    popularity: float = 0.15  # Popularity proximity to seed, not boost
    mood: float = 0.15
    style: float = 0.10
    genre: float = 0.15
    era: float = 0.05
    novelty: float = 0.10
```

### 8.3 Multi-Seed Handling

```python
def compute_seed_centroid(seed_tracks: list[Track]) -> np.ndarray:
    """Average embeddings of multiple seed tracks."""
    embeddings = np.array([t.embedding for t in seed_tracks])
    return embeddings.mean(axis=0)

def aggregate_seed_tags(seed_tracks: list[Track]) -> tuple[set, set, set]:
    """Union of moods, styles, and genres from all seeds."""
    moods = set()
    styles = set()
    genres = set()
    for track in seed_tracks:
        moods.update(track.moods)
        styles.update(track.styles)
        genres.update(track.genres)
    return moods, styles, genres
```

---

## 10. CLI Interface

### 9.1 Command Structure

```
musicseed <command> [options]

Commands:
  import      Import library from Plex database
  enrich      Enrich tracks with Spotify data
  embed       Generate audio embeddings
  recommend   Generate playlist from seed tracks
  status      Show library and enrichment status
```

### 9.2 Command Details

#### `musicseed import`

```
musicseed import [options]

Import metadata from Plex database.

Options:
  --plex-db PATH       Path to Plex SQLite database
                       Default: auto-detect
  --library NAME       Plex library name to import
                       Default: "Music"
  --full               Full re-import (default: incremental)

Example:
  musicseed import --plex-db "~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
```

#### `musicseed enrich`

```
musicseed enrich [options]

Enrich tracks with external metadata (async).

Options:
  --source SOURCE      Enrichment source: spotify (default)
  --batch-size N       Tracks per batch (default: 50)
  --limit N            Max tracks to enrich (default: all)
  --unmatched-only     Only enrich tracks without spotify_id
  --concurrency N      Concurrent async requests (default: 5)

Example:
  musicseed enrich --source spotify --batch-size 100 --concurrency 10
```

#### `musicseed embed`

```
musicseed embed [options]

Generate audio embeddings for tracks.

Options:
  --model MODEL        Embedding model: essentia (default, only option for v1)
  --batch-size N       Tracks per batch (default: 10)
  --limit N            Max tracks to process (default: all)
  --missing-only       Only process tracks without embeddings
  --workers N          Parallel workers (default: 4)

Example:
  musicseed embed --batch-size 20 --workers 8
```

#### `musicseed recommend`

```
musicseed recommend [options]

Generate playlist from seed tracks.

Options:
  --seed TRACK         Seed track (title, or "Artist - Title")
                       Can be specified multiple times
  --seed-id ID         Seed track by database ID
  --limit N            Playlist length (default: 50)
  --playlist NAME      Plex playlist name (default: auto-generated)

  Weights (0.0 - 1.0):
  --w-sonic FLOAT      Sonic similarity weight (default: 0.30)
  --w-popularity FLOAT Popularity proximity weight (default: 0.15)
  --w-mood FLOAT       Mood alignment weight (default: 0.15)
  --w-style FLOAT      Style alignment weight (default: 0.10)
  --w-genre FLOAT      Genre alignment weight (default: 0.15)
  --w-era FLOAT        Era proximity weight (default: 0.05)
  --w-novelty FLOAT    Novelty/unplayed weight (default: 0.10)

  Filters:
  --year-min YEAR      Minimum release year
  --year-max YEAR      Maximum release year
  --artist-max N       Max tracks per artist (default: 3)

Example:
  musicseed recommend \
    --seed "Portishead - Wandering Star" \
    --seed "Massive Attack - Teardrop" \
    --limit 50 \
    --playlist "Late Night Vibes" \
    --w-sonic 0.4 \
    --w-popularity 0.3
```

#### `musicseed status`

```
musicseed status

Show library statistics.

Output:
  Total tracks:           60,000
  With Spotify match:     54,000 (90%)
  With embeddings:        59,400 (99%)
  With MBID (from Plex):  53,154 (89%)

  Play history entries:    48,291
  Unique tracks played:    12,847

  Last import:            2025-01-20 14:32:00
  Last enrichment:        2025-01-20 15:45:00
```

---

## 11. Tech Stack

### 11.1 Core Technologies

| Component | Technology | Version | Rationale |
|-----------|------------|---------|-----------|
| **Language** | Python | 3.11+ | Best ML/audio ecosystem, developer expertise |
| **Package Manager** | uv | Latest | Fast, modern Python package management |
| **Database** | PostgreSQL | 16+ | Robust, pgvector support |
| **Vector Search** | pgvector | 0.6+ | Single DB, good performance at 60K scale |
| **CLI Framework** | Typer | 0.9+ | Clean, type-hinted CLI |
| **CLI Output** | Rich | 13+ | Beautiful terminal formatting |
| **ORM** | SQLAlchemy | 2.0+ | Type-safe, async support |
| **HTTP Client** | httpx | 0.25+ | Async support for Spotify API |
| **Audio Embeddings** | Essentia | 2.1b6+ | MusiCNN model, Apple Silicon native |
| **Config** | PyYAML | 6.0+ | Simple configuration files |

### 11.2 External APIs

| API | Purpose | Auth Method |
|-----|---------|-------------|
| **ListenBrainz API** | Recording listen/user counts by MBID | No auth for popularity lookups |
| **Spotify Web API** | Optional track/artist popularity, ID matching | OAuth client credentials |
| **Plex API** | Playlist creation | Plex token |
| **AcoustID** | Audio fingerprint → MBID (fallback) | API key (free) |
| **MusicBrainz** | Metadata, ID cross-references | No auth (rate limited) |

### 11.3 Development Tools

| Tool | Purpose |
|------|---------|
| **uv** | Package management, virtual environments |
| **Docker** | PostgreSQL + pgvector container |
| **pytest** | Testing |
| **ruff** | Linting and formatting |
| **mypy** | Type checking (optional) |

### 11.4 Audio Embedding Model

| Model | Dimensions | Captures | Status |
|-------|------------|----------|--------|
| **Essentia (MusiCNN)** | 512 | Genre, mood, instrumentation | **Selected** - Apple Silicon native |

### 11.5 Distribution

| Aspect | Decision |
|--------|----------|
| **Method** | Run from source |
| **Invocation** | `uv run musicseed <command>` or installed via `uv pip install -e .` |
| **No packaging** | No PyInstaller/Nuitka binary for v1 |

---

## 12. Configuration

### 12.1 Configuration File

```yaml
# ~/.config/musicseed/config.yaml

database:
  host: localhost
  port: 5432
  name: musicseed
  user: musicseed
  password: ${MUSICSEED_DB_PASSWORD}

plex:
  url: http://localhost:32400
  token: ${PLEX_TOKEN}
  library: Music
  db_path: ~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db

spotify:
  client_id: ${SPOTIFY_CLIENT_ID}
  client_secret: ${SPOTIFY_CLIENT_SECRET}

acoustid:
  api_key: ${ACOUSTID_API_KEY}  # optional, for Tier 3 matching

embedding:
  model: essentia
  batch_size: 10
  workers: 4

enrichment:
  concurrency: 5  # async concurrent requests
  batch_size: 50

logging:
  level: INFO          # file logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
  console: false       # keep CLI/progress output readable by default
  console_level: WARNING

recommendation:
  default_weights:
    sonic: 0.30
    popularity: 0.15
    mood: 0.15
    style: 0.10
    genre: 0.15
    era: 0.05
    novelty: 0.10
  default_limit: 50
  max_tracks_per_artist: 3
```

---

## 13. Implementation Phases

### Phase 1: Foundation (MVP)

**Goal:** Import Plex data, basic CLI, manual playlist testing

- [ ] Project setup (Python, PostgreSQL, pgvector)
- [ ] Database schema creation
- [ ] Plex SQLite importer
  - [ ] metadata_items (tracks, albums, artists)
  - [ ] tags (mood, style, genre, MBID)
  - [ ] metadata_item_views (play history)
  - [ ] media_parts (file paths)
- [ ] Basic CLI structure
- [ ] `musicseed import` command
- [ ] `musicseed status` command

**Deliverable:** Library imported into PostgreSQL, viewable stats

### Phase 2: Enrichment

**Goal:** Spotify popularity data for all matchable tracks

- [ ] Spotify API client (OAuth, rate limiting)
- [ ] Track matching logic (search by artist + title + album)
- [ ] Batch enrichment pipeline
- [ ] `musicseed enrich` command
- [ ] Progress tracking and resumability

**Deliverable:** 80%+ tracks with Spotify popularity

### Phase 3: Embeddings

**Goal:** Audio embeddings for all tracks

- [ ] Essentia integration
- [ ] Batch embedding pipeline
- [ ] pgvector index optimization
- [ ] `musicseed embed` command
- [ ] Progress tracking and resumability

**Deliverable:** All tracks have embeddings, similarity search works

### Phase 4: Recommendations

**Goal:** Seed-based playlist generation

- [ ] Seed resolution (fuzzy track matching)
- [ ] Multi-seed centroid computation
- [ ] Scoring algorithm implementation
- [ ] Artist diversity enforcement
- [ ] `musicseed recommend` command (outputs to console)

**Deliverable:** CLI generates ranked track lists from seeds

### Phase 5: Plex Integration

**Goal:** Create playlists directly in Plex

- [ ] Plex API client
- [ ] Playlist creation/update
- [ ] Track ID mapping (MusicSeed ID → Plex ID)
- [ ] Full `musicseed recommend` with `--playlist`

**Deliverable:** End-to-end workflow complete

### Phase 6: Polish

**Goal:** Production-ready tool

- [ ] Error handling and recovery
- [ ] Logging and diagnostics
- [ ] Configuration validation
- [ ] Documentation
- [ ] Performance optimization (large libraries)

---

## 14. Future Considerations (v2+)

### 13.1 Additional Data Sources

- Discogs popularity (have/want counts)
- Last.fm scrobble data
- MusicBrainz ratings
- Rate Your Music data

### 13.2 API Server

- REST/GraphQL API for external integrations
- Web UI for browsing and playlist creation
- Mobile companion app

### 13.3 Advanced Features

- Playlist "radio mode" (continuous generation)
- Mood/energy curves (playlist pacing)
- Time-aware recommendations (morning vs. night)
- Social features (share playlists, collaborative filtering)

### 13.4 Alternative Embedding Models

- Fine-tuned models on user's listening history
- Multi-modal (audio + lyrics + album art)
- Hierarchical embeddings (track → album → artist)

---

## 15. Appendix

### 14.1 Plex Database Reference

```sql
-- Key tables and their metadata_type values
-- metadata_type 1  = Movie
-- metadata_type 2  = TV Show
-- metadata_type 3  = Season
-- metadata_type 4  = Episode
-- metadata_type 8  = Artist
-- metadata_type 9  = Album
-- metadata_type 10 = Track

-- Tag types in Plex
-- tag_type 1   = Genre
-- tag_type 4   = Label
-- tag_type 8   = Country
-- tag_type 300 = Mood
-- tag_type 301 = Style
-- tag_type 305 = Artist (redundant)
-- tag_type 314 = MusicBrainz ID
-- tag_type 318 = Label (alt)
```

### 14.2 Spotify API Rate Limits

- Standard rate limit: ~180 requests/minute
- Search endpoint: 30 requests/second (burst)
- Batch get tracks: 50 IDs per request
- Batch get audio features: 100 IDs per request

### 14.3 Glossary

| Term | Definition |
|------|------------|
| **Seed track** | Starting track(s) for recommendation generation |
| **Embedding** | Fixed-size vector representing audio characteristics |
| **Centroid** | Average embedding of multiple seed tracks |
| **pgvector** | PostgreSQL extension for vector similarity search |
| **MBID** | MusicBrainz Identifier (UUID format) |
| **Jaccard similarity** | Set overlap metric: |A∩B| / |A∪B| |

---

## 16. Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-01 | Initial draft |
| 1.1 | 2025-01 | Finalized tech stack: Python 3.11+, macOS Apple Silicon, Essentia MusiCNN, async Spotify enrichment, uv package management |
