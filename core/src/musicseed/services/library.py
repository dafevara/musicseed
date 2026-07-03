"""Library service — surface-agnostic entry points for import, DB, and status operations."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from musicseed.config import get_config
from musicseed.db.session import IndexResult, create_indexes, ensure_schema, get_session, init_db
from musicseed.exceptions import NotFoundError
from musicseed.importers.plex import import_from_plex, import_plex_sonic_embeddings


class EnrichmentCoverage(BaseModel):
    tracks_with_mbid: int
    tracks_with_spotify: int
    spotify_attempted: int
    tracks_with_embedding: int
    embeddings_attempted: int
    tracks_with_listenbrainz: int
    listenbrainz_attempted: int


class LibraryStatus(BaseModel):
    db_host: str
    db_port: int
    db_name: str
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


class PlexSonicImportResult(BaseModel):
    available: int
    imported: int
    skipped: int
    invalid: int
    missing: int


def initialize_database() -> None:
    """Create tables and extensions. Idempotent."""
    init_db()


def optimize_database() -> list[IndexResult]:
    """Create performance indexes. Returns per-index results."""
    ensure_schema()
    return create_indexes()


def import_library(
    plex_db_path: Path | None = None,
    library_name: str | None = None,
    full_import: bool = False,
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
        )

    return ImportResult(**result)


def import_plex_sonic(
    plex_db_path: Path | None = None,
    blobs_db_path: Path | None = None,
    library_name: str | None = None,
    overwrite: bool = False,
) -> PlexSonicImportResult:
    """Import Plex sonic analysis vectors.

    Raises:
        NotFoundError: if Plex database or blobs database file does not exist.
    """
    config = get_config()
    db_path = plex_db_path or config.plex.db_path_expanded
    blobs_path = blobs_db_path or db_path.with_name(f"{db_path.stem}.blobs{db_path.suffix}")
    target_library = library_name or config.plex.library

    if not db_path.exists():
        raise NotFoundError(f"Plex database not found at {db_path}")
    if not blobs_path.exists():
        raise NotFoundError(f"Plex blobs database not found at {blobs_path}")

    ensure_schema()
    with get_session() as session:
        stats = import_plex_sonic_embeddings(
            session=session,
            plex_db_path=db_path,
            blobs_db_path=blobs_path,
            library_name=target_library,
            overwrite=overwrite,
        )

    return PlexSonicImportResult(**stats)


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
        tracks_with_embedding = (
            session.query(Track).filter(Track.embedding.isnot(None)).count()
        )
        embeddings_attempted = (
            session.query(Track).filter(Track.embedding_generated.is_(True)).count()
        )
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

    return LibraryStatus(
        db_host=config.database.host,
        db_port=config.database.port,
        db_name=config.database.name,
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
            tracks_with_embedding=tracks_with_embedding,
            embeddings_attempted=embeddings_attempted,
            tracks_with_listenbrainz=tracks_with_listenbrainz,
            listenbrainz_attempted=listenbrainz_attempted,
        ),
    )
