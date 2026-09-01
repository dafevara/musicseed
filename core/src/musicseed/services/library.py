"""Library service — surface-agnostic entry points for import, DB, and status operations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from musicseed.context import MusicSeedContext, get_context
from musicseed.db.models import Job
from musicseed.db.session import IndexResult, create_indexes, ensure_schema, init_db
from musicseed.exceptions import NotFoundError
from musicseed.importers.plex import PlexImporter, import_from_plex


class EnrichmentCoverage(BaseModel):
    """Per-source enrichment coverage counts over the local track library."""

    tracks_with_mbid: int
    tracks_with_spotify: int
    spotify_attempted: int
    tracks_with_sonic: int
    tracks_with_listenbrainz: int
    listenbrainz_attempted: int


class LibraryStatus(BaseModel):
    """Point-in-time statistics for the local library and its configuration."""

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
    import_coverage: ImportCoverage | None = None


class ImportResult(BaseModel):
    """Counts of rows written by one Plex import run."""

    artists: int
    albums: int
    tracks: int
    play_history: int


class CountCompare(BaseModel):
    """Plex vs local row counts for one entity type."""

    plex: int
    local: int

    @property
    def missing(self) -> int:
        """How many Plex rows are not yet imported locally (never negative)."""
        return max(0, self.plex - self.local)


class ImportCoverage(BaseModel):
    """Comparison of Plex library counts against the imported local counts."""

    artists: CountCompare
    albums: CountCompare
    tracks: CountCompare
    ever_succeeded: bool

    @property
    def complete(self) -> bool:
        """True when every Plex artist, album, and track is imported locally."""
        return (
            self.artists.missing == 0
            and self.albums.missing == 0
            and self.tracks.missing == 0
        )

    @property
    def setup_incomplete(self) -> bool:
        """True when no import ever succeeded and coverage is not complete.

        Surfaces use this to detect an interrupted first-time import that
        should be resumed.
        """
        return not self.ever_succeeded and not self.complete


def initialize_database(context: MusicSeedContext | None = None) -> None:
    """Create the SQLite database file and tables. Idempotent.

    Args:
        context: runtime context to use; defaults to the default context.
    """
    init_db(context)


def optimize_database(context: MusicSeedContext | None = None) -> list[IndexResult]:
    """Create performance indexes.

    Args:
        context: runtime context to use; defaults to the default context.

    Returns:
        Per-index results describing success or failure for each index.
    """
    ensure_schema(context)
    return create_indexes(context)


def import_library(
    plex_db_path: Path | None = None,
    library_name: str | None = None,
    full_import: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    context: MusicSeedContext | None = None,
) -> ImportResult:
    """Import metadata from the Plex database into the local library.

    Args:
        plex_db_path: path to the Plex SQLite database; defaults to the
            configured ``plex.db_path``.
        library_name: Plex library to import; defaults to the configured
            ``plex.library``.
        full_import: re-import everything instead of an incremental import.
        progress_callback: optional ``(current, total, phase)`` callback
            invoked as the import progresses.
        should_cancel: optional callable polled by the importer; the import
            stops early when it returns True.
        context: runtime context to use; defaults to the default context.

    Returns:
        Counts of imported artists, albums, tracks, and play history rows.

    Raises:
        NotFoundError: if the Plex database file does not exist.
    """
    ctx = context or get_context()
    config = ctx.config
    db_path = plex_db_path or config.plex.db_path_expanded
    target_library = library_name or config.plex.library

    if not db_path.exists():
        raise NotFoundError(f"Plex database not found at {db_path}")

    with ctx.session() as session:
        result = import_from_plex(
            session=session,
            plex_db_path=db_path,
            library_name=target_library,
            full_import=full_import,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    return ImportResult(**result)


def has_succeeded_import(context: MusicSeedContext | None = None) -> bool:
    """Return True when any import job has ever reached ``succeeded``.

    Returns False (rather than raising) when the database cannot be read.

    Args:
        context: runtime context to use; defaults to the default context.
    """
    ctx = context or get_context()
    try:
        ensure_schema(ctx)
        with ctx.session() as session:
            return (
                session.query(Job)
                .filter(Job.kind == "import", Job.state == "succeeded")
                .first()
                is not None
            )
    except Exception:
        return False


def get_import_coverage(
    context: MusicSeedContext | None = None,
) -> ImportCoverage | None:
    """Compare MusicSeed artist/album/track counts to the configured Plex library.

    Args:
        context: runtime context to use; defaults to the default context.

    Returns:
        The coverage comparison, or None when the Plex database cannot be
        read. Does not raise.
    """
    ctx = context or get_context()
    config = ctx.config
    plex_db = config.plex.db_path_expanded
    if not plex_db.exists():
        return None

    importer = PlexImporter(plex_db, config.plex.library)
    try:
        plex = importer.get_counts()
    except Exception:
        return None
    finally:
        importer.close()

    from musicseed.db.models import Album, Artist, Track

    try:
        ensure_schema(ctx)
        with ctx.session() as session:
            local_artists = session.query(Artist).count()
            local_albums = session.query(Album).count()
            local_tracks = session.query(Track).count()
    except Exception:
        local_artists = local_albums = local_tracks = 0

    return ImportCoverage(
        artists=CountCompare(plex=plex["artists"], local=local_artists),
        albums=CountCompare(plex=plex["albums"], local=local_albums),
        tracks=CountCompare(plex=plex["tracks"], local=local_tracks),
        ever_succeeded=has_succeeded_import(context=ctx),
    )


def _count_tracks_with_sonic(session) -> int:
    """Count local tracks that have a stored Plex sonic vector."""
    from musicseed.db.models import Track, TrackVector

    return (
        session.query(Track)
        .join(TrackVector, Track.plex_id == TrackVector.plex_id)
        .count()
    )


def get_status(context: MusicSeedContext | None = None) -> LibraryStatus:
    """Return library statistics and enrichment coverage.

    Args:
        context: runtime context to use; defaults to the default context.

    Returns:
        Entity counts (artists, albums, tracks, plays, tags), per-source
        enrichment coverage, import coverage against the configured Plex
        library, and the resolved configuration paths.
    """
    from sqlalchemy import or_

    from musicseed.db.models import Album, Artist, Genre, Mood, PlayHistory, Style, Track

    ctx = context or get_context()
    config = ctx.config
    ensure_schema(ctx)

    with ctx.session() as session:
        artist_count = session.query(Artist).count()
        album_count = session.query(Album).count()
        track_count = session.query(Track).count()
        play_count = session.query(PlayHistory).count()

        tracks_with_mbid = session.query(Track).filter(Track.mbid.isnot(None)).count()
        tracks_with_spotify = session.query(Track).filter(Track.spotify_id.isnot(None)).count()
        spotify_attempted = session.query(Track).filter(Track.spotify_matched.is_(True)).count()
        tracks_with_sonic = _count_tracks_with_sonic(session)
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
        import_coverage=get_import_coverage(context=ctx),
        enrichment=EnrichmentCoverage(
            tracks_with_mbid=tracks_with_mbid,
            tracks_with_spotify=tracks_with_spotify,
            spotify_attempted=spotify_attempted,
            tracks_with_sonic=tracks_with_sonic,
            tracks_with_listenbrainz=tracks_with_listenbrainz,
            listenbrainz_attempted=listenbrainz_attempted,
        ),
    )
