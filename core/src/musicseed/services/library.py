"""Library service — surface-agnostic entry points for import, DB, and status operations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from musicseed.config import get_config
from musicseed.db.session import IndexResult, create_indexes, ensure_schema, get_session, init_db
from musicseed.exceptions import NotFoundError
from musicseed.importers.plex import import_from_plex
from musicseed.sonic import get_sonic_vectors

_sonic_count_cache: tuple[tuple[str, int, int], int] | None = None


class EnrichmentCoverage(BaseModel):
    tracks_with_mbid: int
    tracks_with_spotify: int
    spotify_attempted: int
    tracks_with_sonic: int
    tracks_with_listenbrainz: int
    listenbrainz_attempted: int


class LibraryStatus(BaseModel):
    db_path: str
    db_size_bytes: int | None
    plex_url: str
    plex_db: str
    plex_library: str
    artist_count: int
    album_count: int
    track_count: int
    play_count: int
    genre_count: int
    mood_count: int
    style_count: int
    enrichment: EnrichmentCoverage


class ImportResult(BaseModel):
    artists: int
    albums: int
    tracks: int
    play_history: int


def initialize_database() -> None:
    """Create the SQLite database file and tables. Idempotent."""
    init_db()


def optimize_database() -> list[IndexResult]:
    """Create performance indexes. Returns per-index results."""
    ensure_schema()
    return create_indexes()


def import_library(
    plex_db_path: Path | None = None,
    library_name: str | None = None,
    full_import: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ImportResult:
    """Import metadata from Plex database.

    Raises:
        NotFoundError: if the Plex database file does not exist.
    """
    config = get_config()
    db_path = plex_db_path or config.plex.db_path_expanded
    target_library = library_name or config.plex.library

    if not db_path.exists():
        raise NotFoundError(f"Plex database not found at {db_path}")

    with get_session() as session:
        result = import_from_plex(
            session=session,
            plex_db_path=db_path,
            library_name=target_library,
            full_import=full_import,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    return ImportResult(**result)


def _count_tracks_with_sonic(session, track_count: int) -> int:
    """Count local tracks Plex currently has a sonic vector for.

    Returns 0 rather than raising when Plex's databases are unavailable, so
    status still renders the rest of the library.

    The count is cached by ``(db_path, track_count, vector_count)``: it only
    changes when tracks are imported (track_count changes) or Plex analyzes
    more items (vector count changes), so the full ``tracks.plex_id`` scan is
    avoided on repeat dashboard polls.
    """
    from musicseed.db.models import Track

    global _sonic_count_cache

    try:
        vectors = get_sonic_vectors()
    except NotFoundError:
        return 0

    plex_ids = vectors.plex_ids
    db_key = str(get_config().database.path_expanded)
    cache_key = (db_key, track_count, len(plex_ids))
    if _sonic_count_cache is not None and _sonic_count_cache[0] == cache_key:
        return _sonic_count_cache[1]

    track_plex_ids = {
        row[0]
        for row in session.query(Track.plex_id).filter(Track.plex_id.isnot(None))
    }
    count = len(plex_ids & track_plex_ids)
    _sonic_count_cache = (cache_key, count)
    return count


def get_status() -> LibraryStatus:
    """Return library statistics and enrichment coverage."""
    from sqlalchemy import or_

    from musicseed.db.models import Album, Artist, Genre, Mood, PlayHistory, Style, Track

    config = get_config()
    ensure_schema()

    with get_session() as session:
        artist_count = session.query(Artist).count()
        album_count = session.query(Album).count()
        track_count = session.query(Track).count()
        play_count = session.query(PlayHistory).count()

        tracks_with_mbid = session.query(Track).filter(Track.mbid.isnot(None)).count()
        tracks_with_spotify = session.query(Track).filter(Track.spotify_id.isnot(None)).count()
        spotify_attempted = session.query(Track).filter(Track.spotify_matched.is_(True)).count()
        tracks_with_sonic = _count_tracks_with_sonic(session, track_count)
        tracks_with_listenbrainz = (
            session.query(Track)
            .filter(
                or_(
                    Track.listenbrainz_listen_count.isnot(None),
                    Track.listenbrainz_listener_count.isnot(None),
                )
            )
            .count()
        )
        listenbrainz_attempted = (
            session.query(Track).filter(Track.listenbrainz_matched.is_(True)).count()
        )

        genre_count = session.query(Genre).count()
        mood_count = session.query(Mood).count()
        style_count = session.query(Style).count()

    db_path = config.database.path_expanded
    return LibraryStatus(
        db_path=str(db_path),
        db_size_bytes=db_path.stat().st_size if db_path.exists() else None,
        plex_url=config.plex.url,
        plex_db=str(config.plex.db_path_expanded),
        plex_library=config.plex.library,
        artist_count=artist_count,
        album_count=album_count,
        track_count=track_count,
        play_count=play_count,
        genre_count=genre_count,
        mood_count=mood_count,
        style_count=style_count,
        enrichment=EnrichmentCoverage(
            tracks_with_mbid=tracks_with_mbid,
            tracks_with_spotify=tracks_with_spotify,
            spotify_attempted=spotify_attempted,
            tracks_with_sonic=tracks_with_sonic,
            tracks_with_listenbrainz=tracks_with_listenbrainz,
            listenbrainz_attempted=listenbrainz_attempted,
        ),
    )
