"""Database session management.

Pure engine/session factory functions live here; the module-level
``get_engine``/``get_session``/``reset_engine`` conveniences delegate to the
default ``MusicSeedContext`` (see ``musicseed.context``).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Generator

from pydantic import BaseModel
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from musicseed.db.models import Base

if TYPE_CHECKING:
    from musicseed.context import MusicSeedContext


class IndexResult(BaseModel):
    """Result from one index creation statement."""

    model_config = {"frozen": True}

    name: str
    success: bool
    error: str | None = None


def create_engine_for_url(url: str) -> Engine:
    """Create a SQLite engine with MusicSeed's connect-time pragmas.

    Args:
        url: SQLAlchemy connection URL (``sqlite:///...``).

    Returns:
        A new engine that enables WAL journaling, foreign keys, and a busy
        timeout on every connection.
    """
    engine = create_engine(url, echo=False)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker:
    """Create a session factory bound to ``engine``.

    Uses ``expire_on_commit=False`` for internal multi-step workflows. Public
    services still project scalar DTOs inside their session; this setting does
    not make unloaded ORM relationships safe to access after session closure.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_engine() -> Engine:
    """Get the default context's SQLite engine (created on first use)."""
    from musicseed.context import get_context

    return get_context().engine


def get_session_factory() -> sessionmaker:
    """Get the default context's session factory."""
    from musicseed.context import get_context

    return get_context().session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get a database session from the default context as a context manager."""
    from musicseed.context import get_context

    with get_context().session() as session:
        yield session


def init_db(context: MusicSeedContext | None = None) -> None:
    """Initialize the database schema, creating the DB file's parent dir if needed.

    Args:
        context: runtime context to operate on; defaults to the default
            context.
    """
    from musicseed.context import get_context

    ctx = context or get_context()
    ctx.config.database.path_expanded.parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(ctx.engine)
    ensure_schema(ctx)


# (table, column, column DDL) for lightweight additive migrations on existing files.
_ADDITIVE_COLUMNS = [
    ("tracks", "popularity_source", "VARCHAR(50)"),
    ("tracks", "listenbrainz_listen_count", "BIGINT"),
    ("tracks", "listenbrainz_listener_count", "INTEGER"),
    ("tracks", "listenbrainz_matched", "BOOLEAN DEFAULT FALSE"),
    ("jobs", "result_summary", "TEXT"),
    ("jobs", "pid", "INTEGER"),
    ("jobs", "progress_phases", "TEXT"),
]


def ensure_schema(context: MusicSeedContext | None = None) -> None:
    """Apply lightweight additive schema updates for existing local databases.

    New tables are created via ``Base.metadata.create_all(checkfirst=True)``;
    additive column migrations are handled per-table via the PRAGMA list.

    Args:
        context: runtime context to operate on; defaults to the default
            context.
    """
    from musicseed.context import get_context

    ctx = context or get_context()
    Base.metadata.create_all(ctx.engine, checkfirst=True)
    with ctx.engine.connect() as conn:
        for table, column, column_ddl in _ADDITIVE_COLUMNS:
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            if existing and column not in existing:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {column_ddl}")
                )
        conn.commit()


def create_indexes(context: MusicSeedContext | None = None) -> list[IndexResult]:
    """Create additional indexes (call after initial data load).

    Args:
        context: runtime context to operate on; defaults to the default
            context.

    Returns:
        Per-index results describing success or failure for each index.
    """
    from musicseed.context import get_context

    ctx = context or get_context()

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
    with ctx.engine.connect() as conn:
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
    """Drop the default context (engine, session factory, and sonic cache).

    Preserved as a test/config-change hook; with explicit contexts the
    preferred reset is to construct and install a fresh ``MusicSeedContext``.
    """
    from musicseed.context import reset_context

    reset_context()
