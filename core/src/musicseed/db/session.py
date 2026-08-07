"""Database session management."""

from contextlib import contextmanager
from typing import Generator

from pydantic import BaseModel
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from musicseed.config import get_config
from musicseed.db.models import Base

# Global engine and session factory
_engine = None
_SessionLocal = None


class IndexResult(BaseModel):
    """Result from one index creation statement."""

    model_config = {"frozen": True}

    name: str
    success: bool
    error: str | None = None


def get_engine():
    """Get or create the SQLite database engine."""
    global _engine
    if _engine is None:
        config = get_config()
        engine = create_engine(config.database.url, echo=False)

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

        _engine = engine
    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
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
    """Initialize the database schema, creating the DB file's parent dir if needed."""
    config = get_config()
    config.database.path_expanded.parent.mkdir(parents=True, exist_ok=True)

    engine = get_engine()
    Base.metadata.create_all(engine)
    ensure_schema()


# (table, column, column DDL) for lightweight additive migrations on existing files.
_ADDITIVE_COLUMNS = [
    ("tracks", "popularity_source", "VARCHAR(50)"),
    ("tracks", "listenbrainz_listen_count", "BIGINT"),
    ("tracks", "listenbrainz_listener_count", "INTEGER"),
    ("tracks", "listenbrainz_matched", "BOOLEAN DEFAULT FALSE"),
]


def ensure_schema() -> None:
    """Apply lightweight additive schema updates for existing local databases.

    New tables are created via ``Base.metadata.create_all(checkfirst=True)``;
    additive column migrations are handled per-table via the PRAGMA list.
    """
    engine = get_engine()
    Base.metadata.create_all(engine, checkfirst=True)
    with engine.connect() as conn:
        for table, column, column_ddl in _ADDITIVE_COLUMNS:
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            if existing and column not in existing:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {column_ddl}")
                )
        conn.commit()


def create_indexes() -> list[IndexResult]:
    """Create additional indexes (call after initial data load)."""
    engine = get_engine()

    indexes = [
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
            "ON tracks(id) "
            "WHERE mbid IS NOT NULL AND listenbrainz_matched IS NOT TRUE",
        ),
        (
            "idx_tracks_spotify_queue",
            "CREATE INDEX IF NOT EXISTS idx_tracks_spotify_queue "
            "ON tracks(id) WHERE spotify_matched IS NOT TRUE",
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
