"""Library service — surface-agnostic entry points for import, DB, and status operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel

from musicseed.context import MusicSeedContext, get_context
from musicseed.db.session import IndexResult, create_indexes, ensure_schema, init_db
from musicseed.exceptions import NotFoundError
from musicseed.importers.plex import PlexImporter, import_from_plex
from musicseed.plex_db_source import resolve_plex_dbs
from musicseed.services.import_state import checkpoint, read_import_state, snapshot_id
from musicseed.services.jobs import exclusive_writer


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
    verified: bool = False

    @property
    def complete(self) -> bool:
        """True when the source completed and counts match the current snapshot."""
        return (
            self.verified
            and self.artists.missing == 0
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


@exclusive_writer("import")
def import_library(
    plex_db_path: Path | None = None,
    plex_db_ssh: str | None = None,
    library_name: str | None = None,
    full_import: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    context: MusicSeedContext | None = None,
) -> ImportResult:
    """Import metadata from the Plex database into the local library.

    Args:
        plex_db_path: path to the Plex SQLite database; overrides the
            configured source when given.
        plex_db_ssh: scp-style SSH target of a remote Plex database
            directory; overrides ``plex.db_ssh_target`` when given.
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
    if plex_db_path is not None or plex_db_ssh is not None or library_name is not None:
        cfg = ctx.config.model_copy(deep=True)
        if plex_db_path is not None:
            cfg.plex.db_path = str(plex_db_path)
            cfg.plex.db_ssh_target = ""
        elif plex_db_ssh is not None:
            cfg.plex.db_ssh_target = plex_db_ssh
        if library_name is not None:
            cfg.plex.library = library_name
        ctx = MusicSeedContext(cfg)
    ensure_schema(ctx)
    cancelled = False

    def is_cancelled() -> bool:
        nonlocal cancelled
        cancelled = cancelled or (should_cancel is not None and should_cancel())
        return cancelled

    def on_progress(current: int, total: int, phase: str) -> None:
        checkpoint(ctx, "running", phase=phase, processed=current)
        if progress_callback is not None:
            progress_callback(current, total, phase)

    checkpoint(ctx, "running", phase="reading source", processed=0)
    try:
        if is_cancelled():
            checkpoint(ctx, "canceled")
            return ImportResult(artists=0, albums=0, tracks=0, play_history=0)
        if ctx.config.plex.db_ssh_target:
            on_progress(0, 0, "downloading Plex database")
        db_path = resolve_plex_dbs(ctx.config, refresh=True).library_db
        if not db_path.exists():
            raise NotFoundError(f"Plex database not found at {db_path}")
        with closing(PlexImporter(db_path, ctx.config.plex.library)) as importer:
            expected = importer.get_counts()
        checkpoint(ctx, "running", snapshot=snapshot_id(db_path), expected=expected)
        with ctx.session() as session:
            result = import_from_plex(
                session=session, plex_db_path=db_path, library_name=ctx.config.plex.library,
                full_import=full_import, progress_callback=on_progress, should_cancel=is_cancelled,
            )
        if cancelled:
            checkpoint(ctx, "canceled")
        else:
            checkpoint(ctx, "complete", phase="finished")
        return ImportResult(**result)
    except BaseException as error:
        checkpoint(ctx, "canceled" if isinstance(error, KeyboardInterrupt) else "failed")
        raise


def has_succeeded_import(context: MusicSeedContext | None = None) -> bool:
    """Whether this source/library completed an import, independent of job history."""
    state = read_import_state(context or get_context())
    return bool(state and state["completed_at"])


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
    try:
        plex_db = resolve_plex_dbs(config, refresh=False).library_db
    except NotFoundError:
        return None
    if not plex_db.exists():
        return None

    importer = PlexImporter(plex_db, config.plex.library)
    try:
        plex = importer.get_counts()
    except Exception:
        return None
    finally:
        importer.close()

    try:
        path = ctx.config.database.path_expanded.resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            local_artists = conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
            local_albums = conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
            local_tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        state = read_import_state(ctx)
        verified = bool(state and state["state"] == "complete"
                        and state["snapshot"] == snapshot_id(plex_db))
    except (sqlite3.Error, OSError):
        return None

    return ImportCoverage(
        artists=CountCompare(plex=plex["artists"], local=local_artists),
        albums=CountCompare(plex=plex["albums"], local=local_albums),
        tracks=CountCompare(plex=plex["tracks"], local=local_tracks),
        ever_succeeded=has_succeeded_import(context=ctx),
        verified=verified,
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
