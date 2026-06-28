"""Database session management."""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from musicseed.config import get_config
from musicseed.db.models import Base

# Global engine and session factory
_engine = None
_SessionLocal = None


@dataclass(frozen=True)
class IndexResult:
    """Result from one index creation statement."""

    name: str
    success: bool
    error: str | None = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        config = get_config()
        _engine = create_engine(config.database.url, echo=False)
    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get a database session as a context manager."""
    session_local = get_session_factory()
    session = session_local()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Initialize the database schema and extensions."""
    engine = get_engine()

    # Enable pgvector extension
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # Create all tables
    Base.metadata.create_all(engine)
    ensure_schema()


def ensure_schema() -> None:
    """Apply lightweight additive schema updates for existing local databases."""
    engine = get_engine()
    statements = [
        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS popularity_source VARCHAR(50)",
        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS listenbrainz_listen_count BIGINT",
        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS listenbrainz_listener_count INTEGER",
        (
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS "
            "listenbrainz_matched BOOLEAN DEFAULT FALSE"
        ),
    ]
    with engine.connect() as conn:
        for statement in statements:
            conn.execute(text(statement))
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pg_attribute a
                        JOIN pg_class c ON c.oid = a.attrelid
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public'
                          AND c.relname = 'tracks'
                          AND a.attname = 'embedding'
                          AND format_type(a.atttypid, a.atttypmod) = 'vector(512)'
                    ) THEN
                        DROP INDEX IF EXISTS idx_tracks_embedding;
                        UPDATE tracks
                        SET embedding = NULL,
                            embedding_model = NULL,
                            embedding_generated = FALSE
                        WHERE embedding IS NOT NULL;
                        ALTER TABLE tracks
                        ALTER COLUMN embedding TYPE vector(200)
                        USING NULL::vector(200);
                    END IF;
                END $$;
                """
            )
        )
        conn.commit()


def create_indexes() -> list[IndexResult]:
    """Create additional indexes (call after initial data load)."""
    engine = get_engine()

    indexes = [
        ("extension_pg_trgm", "CREATE EXTENSION IF NOT EXISTS pg_trgm"),
        # Vector similarity search (IVFFlat for ~60K tracks)
        (
            "idx_tracks_embedding",
            """
            CREATE INDEX IF NOT EXISTS idx_tracks_embedding ON tracks
            USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
            """,
        ),
        # Common queries
        (
            "idx_tracks_artist",
            "CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist_id)",
        ),
        ("idx_tracks_album", "CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_id)"),
        ("idx_tracks_plex_id", "CREATE INDEX IF NOT EXISTS idx_tracks_plex_id ON tracks(plex_id)"),
        ("idx_albums_artist", "CREATE INDEX IF NOT EXISTS idx_albums_artist ON albums(artist_id)"),
        (
            "idx_tracks_spotify_id",
            "CREATE INDEX IF NOT EXISTS idx_tracks_spotify_id ON tracks(spotify_id)",
        ),
        ("idx_tracks_mbid", "CREATE INDEX IF NOT EXISTS idx_tracks_mbid ON tracks(mbid)"),
        (
            "idx_tracks_popularity",
            "CREATE INDEX IF NOT EXISTS idx_tracks_popularity ON tracks(popularity_score DESC)",
        ),
        (
            "idx_tracks_popularity_source",
            "CREATE INDEX IF NOT EXISTS idx_tracks_popularity_source ON tracks(popularity_source)",
        ),
        (
            "idx_tracks_listenbrainz_listen_count",
            "CREATE INDEX IF NOT EXISTS idx_tracks_listenbrainz_listen_count "
            "ON tracks(listenbrainz_listen_count DESC)",
        ),
        ("idx_tracks_year", "CREATE INDEX IF NOT EXISTS idx_tracks_year ON tracks(year)"),
        (
            "idx_artists_spotify_id",
            "CREATE INDEX IF NOT EXISTS idx_artists_spotify_id ON artists(spotify_id)",
        ),
        ("idx_artists_mbid", "CREATE INDEX IF NOT EXISTS idx_artists_mbid ON artists(mbid)"),
        (
            "idx_artists_plex_id",
            "CREATE INDEX IF NOT EXISTS idx_artists_plex_id ON artists(plex_id)",
        ),
        (
            "idx_albums_spotify_id",
            "CREATE INDEX IF NOT EXISTS idx_albums_spotify_id ON albums(spotify_id)",
        ),
        ("idx_albums_plex_id", "CREATE INDEX IF NOT EXISTS idx_albums_plex_id ON albums(plex_id)"),
        (
            "idx_play_history_track",
            "CREATE INDEX IF NOT EXISTS idx_play_history_track ON play_history(track_id)",
        ),
        (
            "idx_play_history_plex_view_id",
            "CREATE INDEX IF NOT EXISTS idx_play_history_plex_view_id "
            "ON play_history(plex_view_id)",
        ),
        (
            "idx_play_history_played_at",
            "CREATE INDEX IF NOT EXISTS idx_play_history_played_at "
            "ON play_history(played_at DESC)",
        ),
        (
            "idx_track_moods_mood_track",
            "CREATE INDEX IF NOT EXISTS idx_track_moods_mood_track "
            "ON track_moods(mood_id, track_id)",
        ),
        (
            "idx_track_styles_style_track",
            "CREATE INDEX IF NOT EXISTS idx_track_styles_style_track "
            "ON track_styles(style_id, track_id)",
        ),
        (
            "idx_track_genres_genre_track",
            "CREATE INDEX IF NOT EXISTS idx_track_genres_genre_track "
            "ON track_genres(genre_id, track_id)",
        ),
        (
            "idx_tracks_listenbrainz_queue",
            "CREATE INDEX IF NOT EXISTS idx_tracks_listenbrainz_queue "
            "ON tracks(id) INCLUDE (mbid) "
            "WHERE mbid IS NOT NULL AND listenbrainz_matched IS NOT TRUE",
        ),
        (
            "idx_tracks_spotify_queue",
            "CREATE INDEX IF NOT EXISTS idx_tracks_spotify_queue "
            "ON tracks(id) WHERE spotify_matched IS NOT TRUE",
        ),
        (
            "idx_tracks_embedding_queue",
            "CREATE INDEX IF NOT EXISTS idx_tracks_embedding_queue "
            "ON tracks(id) WHERE file_path IS NOT NULL AND embedding_generated IS NOT TRUE",
        ),
        (
            "idx_artists_name_trgm",
            "CREATE INDEX IF NOT EXISTS idx_artists_name_trgm "
            "ON artists USING gin (name gin_trgm_ops)",
        ),
        (
            "idx_albums_title_trgm",
            "CREATE INDEX IF NOT EXISTS idx_albums_title_trgm "
            "ON albums USING gin (title gin_trgm_ops)",
        ),
        (
            "idx_tracks_title_trgm",
            "CREATE INDEX IF NOT EXISTS idx_tracks_title_trgm "
            "ON tracks USING gin (title gin_trgm_ops)",
        ),
    ]

    results: list[IndexResult] = []
    with engine.connect() as conn:
        for index_name, index_sql in indexes:
            try:
                conn.execute(text(index_sql))
                conn.commit()
                results.append(IndexResult(name=index_name, success=True))
            except Exception as e:
                conn.rollback()
                results.append(IndexResult(name=index_name, success=False, error=str(e)))

    return results


def reset_engine() -> None:
    """Reset the engine (useful for testing or config changes)."""
    global _engine, _SessionLocal
    if _engine:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
