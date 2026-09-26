"""Async enrichment pipelines for Spotify metadata and ListenBrainz popularity.

The public entry point is ``services.enrichment.enrich_tracks`` — a
synchronous wrapper that runs these coroutines via ``asyncio.run``. This
module holds the async internals of the enrichment story line:

    select → batch-fetch → write → normalize

Each source has its own runner that shares that shape:

* **Spotify** (``run_spotify_enrichment``) — searches for tracks by title/
  artist/album and writes ``spotify_id``, ``spotify_popularity``, and a
  normalized ``popularity_score`` onto each ``Track``.
* **ListenBrainz** (``run_listenbrainz_enrichment``) — fetches listen/user
  counts for tracks that already have a recording MBID, then
  ``normalize_listenbrainz_popularity`` rescales those counts into
  ``popularity_score``.

Both runners select their work queue with the read-only
``get_tracks_to_enrich`` / ``get_tracks_for_listenbrainz`` helpers, then
stream batches. Each batch opens and closes its own session so the SQLite
write lock is held only for the duration of one batch, never the whole run.
Cancellation is cooperative: the ``should_cancel`` callback is polled between
batches.
"""

import math
from collections.abc import Callable
from contextlib import AbstractContextManager

from pydantic import BaseModel
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from sqlalchemy.orm import Session

from musicseed.db.models import Album, Artist, Track
from musicseed.db.session import get_session
from musicseed.enrichers.listenbrainz import ListenBrainzClient
from musicseed.enrichers.spotify import SpotifyClient
from musicseed.logging_config import get_logger

logger = get_logger("enrichers.pipeline")
console = Console()

# A zero-argument callable that opens a session (commit/rollback/close): either
# the default context's ``get_session`` or a context's bound ``session`` method.
SessionScope = Callable[[], AbstractContextManager[Session]]


class EnrichmentStats(BaseModel):
    """Statistics from enrichment run."""

    total: int
    matched: int
    unmatched: int
    errors: int


def apply_metadata_filters(query, artist: str | None = None, album: str | None = None):
    """Apply optional artist/album filters to an enrichment query."""
    if artist:
        query = query.filter(Artist.name.ilike(to_ilike_pattern(artist), escape="\\"))
    if album:
        query = query.filter(Album.title.ilike(to_ilike_pattern(album), escape="\\"))
    return query


def to_ilike_pattern(value: str) -> str:
    """Convert a user filter into an ILIKE pattern.

    Plain text keeps contains semantics. Shell-style wildcards are supported:
    `*` maps to `%` and `?` maps to `_`.
    """
    has_wildcards = "*" in value or "?" in value
    escaped = []
    for char in value:
        if char == "*":
            escaped.append("%")
        elif char == "?":
            escaped.append("_")
        elif char in {"%", "_", "\\"}:
            escaped.append(f"\\{char}")
        else:
            escaped.append(char)

    pattern = "".join(escaped)
    if has_wildcards:
        return pattern
    return f"%{pattern}%"


def get_tracks_to_enrich(
    session: Session,
    limit: int | None = None,
    unattempted_only: bool = False,
    artist: str | None = None,
    album: str | None = None,
) -> list[dict]:
    """Select the Spotify enrichment work queue.

    Returns tracks joined to their artist/album names so the search client has
    the fields it needs. Rows are plain dicts, so they survive the opening
    session closing before the async fetch begins.

    Args:
        session: open database session.
        limit: maximum number of tracks to return (None for all).
        unattempted_only: when True, only tracks whose ``spotify_matched`` is
            false/null (i.e. not yet attempted).
        artist: optional artist-name filter (ILIKE pattern).
        album: optional album-title filter (ILIKE pattern).

    Returns:
        A list of ``{"id", "title", "artist", "album", "duration_ms"}``
        dicts, one per selected track.
    """
    query = session.query(
        Track.id,
        Track.title,
        Track.duration_ms,
        Artist.name.label("artist_name"),
        Album.title.label("album_title"),
    ).outerjoin(Artist, Track.artist_id == Artist.id
    ).outerjoin(Album, Track.album_id == Album.id)

    query = apply_metadata_filters(query, artist=artist, album=album)

    if unattempted_only:
        query = query.filter(
            (Track.spotify_matched.is_(False)) | (Track.spotify_matched.is_(None))
        )

    if limit:
        query = query.limit(limit)

    tracks = []
    for row in query:
        tracks.append({
            "id": row.id,
            "title": row.title,
            "artist": row.artist_name or "Unknown Artist",
            "album": row.album_title,
            "duration_ms": row.duration_ms,
        })

    return tracks


def get_tracks_for_listenbrainz(
    session: Session,
    limit: int | None = None,
    unattempted_only: bool = False,
    artist: str | None = None,
    album: str | None = None,
) -> list[dict]:
    """Select the ListenBrainz enrichment work queue.

    Only tracks with a recording MBID are eligible, because ListenBrainz
    popularity is keyed by MusicBrainz recording id. Rows are
    ``{"id", "mbid"}`` dicts.

    Args:
        session: open database session.
        limit: maximum number of tracks to return (None for all).
        unattempted_only: when True, only tracks whose
            ``listenbrainz_matched`` is false/null (not yet attempted).
        artist: optional artist-name filter (ILIKE pattern).
        album: optional album-title filter (ILIKE pattern).

    Returns:
        A list of ``{"id", "mbid"}`` dicts, one per selected track.
    """
    query = (
        session.query(Track.id, Track.mbid)
        .outerjoin(Artist, Track.artist_id == Artist.id)
        .outerjoin(Album, Track.album_id == Album.id)
        .filter(Track.mbid.isnot(None))
    )

    query = apply_metadata_filters(query, artist=artist, album=album)

    if unattempted_only:
        query = query.filter(
            (Track.listenbrainz_matched.is_(False))
            | (Track.listenbrainz_matched.is_(None))
        )

    if limit:
        query = query.limit(limit)

    return [{"id": row.id, "mbid": str(row.mbid)} for row in query]


def normalize_listenbrainz_popularity(session: Session) -> None:
    """Normalize raw ListenBrainz listen counts into Track.popularity_score."""
    tracks = (
        session.query(Track)
        .filter(Track.listenbrainz_listen_count.isnot(None))
        .all()
    )
    max_count = max((track.listenbrainz_listen_count or 0 for track in tracks), default=0)
    if max_count <= 0:
        return

    # Log-scale against the library max; the +1 keeps a zero count defined (maps to 0.0).
    max_log = math.log10(max_count + 1)
    for track in tracks:
        listen_count = track.listenbrainz_listen_count or 0
        track.popularity_score = math.log10(listen_count + 1) / max_log
        track.popularity_source = "listenbrainz"
    session.commit()


async def enrich_tracks_with_listenbrainz(
    tracks: list[dict],
    listenbrainz_client: ListenBrainzClient,
    progress: Progress,
    batch_size: int,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    session_scope: SessionScope | None = None,
) -> tuple[int, int, int]:
    """Enrich tracks with ListenBrainz recording listen/user counts.

    Each batch opens and closes its own session so the SQLite write lock is
    only held for the duration of a single batch, not the whole run.
    """
    total = len(tracks)
    task = progress.add_task(
        "[cyan]Fetching ListenBrainz popularity...",
        total=total,
    )

    matched = 0
    unmatched = 0
    errors = 0
    processed = 0
    cancelled = False
    scope = session_scope or get_session

    for start in range(0, total, batch_size):
        if should_cancel is not None and should_cancel():
            cancelled = True
            logger.info("Cancellation requested — stopping ListenBrainz enrichment")
            break
        batch = tracks[start : start + batch_size]
        mbids = [track["mbid"] for track in batch]
        id_by_mbid = {track["mbid"]: track["id"] for track in batch}

        try:
            # Fetch outside any session; the write lock is taken only for the short write below.
            results = await listenbrainz_client.get_recording_popularity(mbids)
            with scope() as session:
                for result in results:
                    track = session.get(Track, id_by_mbid[result.recording_mbid])
                    if track is None:
                        progress.advance(task)
                        processed += 1
                        continue

                    track.listenbrainz_matched = True
                    if result.total_listen_count is not None or result.total_user_count is not None:
                        track.listenbrainz_listen_count = result.total_listen_count
                        track.listenbrainz_listener_count = result.total_user_count
                        matched += 1
                    else:
                        unmatched += 1
                    progress.advance(task)
                    processed += 1
            if progress_callback:
                progress_callback(processed, total, "enriching via ListenBrainz…")
        except Exception as e:
            logger.error(f"ListenBrainz batch failed: {e}")
            errors += len(batch)
            processed += len(batch)
            progress.advance(task, advance=len(batch))

    if not cancelled:
        # Normalize once at the end over the full set, so the max is stable.
        with scope() as session:
            normalize_listenbrainz_popularity(session)
    return matched, unmatched, errors


async def enrich_tracks(
    tracks: list[dict],
    spotify_client: SpotifyClient,
    progress: Progress,
    batch_size: int = 100,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    session_scope: SessionScope | None = None,
) -> tuple[int, int, int]:
    """Enrich tracks via Spotify search.

    Each batch opens and closes its own session so the SQLite write lock is
    only held for the duration of a single batch, not the whole run.

    Args:
        tracks: List of tracks to search
        spotify_client: Spotify client (with throttling)
        progress: Rich progress bar
        batch_size: Number of tracks processed per session (commit unit)
        progress_callback: Optional callback(current, total, message) for job progress
        should_cancel: Optional callback returning True when the job was canceled

    Returns:
        Tuple of (matched count, unmatched count, error count)
    """
    total = len(tracks)
    task = progress.add_task(
        "[cyan]Searching Spotify (1 req/sec)...",
        total=total,
    )

    matched = 0
    unmatched = 0
    errors = 0
    processed = 0
    scope = session_scope or get_session

    for start in range(0, total, batch_size):
        if should_cancel is not None and should_cancel():
            logger.info("Cancellation requested — stopping Spotify enrichment")
            break
        chunk = tracks[start : start + batch_size]
        # Write each batch in its own session; the await happens before the write lock is taken.
        with scope() as session:
            for track_data in chunk:
                try:
                    result = await spotify_client.match_track(
                        title=track_data["title"],
                        artist=track_data["artist"],
                        album=track_data.get("album"),
                        duration_ms=track_data.get("duration_ms"),
                    )

                    track = session.get(Track, track_data["id"])
                    if track:
                        track.spotify_matched = True  # Attempted even on a miss.

                        if result.matched and result.spotify_track:
                            track.spotify_id = result.spotify_track.spotify_id
                            track.spotify_popularity = result.spotify_track.popularity
                            track.popularity_score = result.spotify_track.popularity / 100
                            track.popularity_source = "spotify"
                            track.match_tier = 2  # Spotify search match
                            matched += 1
                            logger.debug(
                                f"Matched '{track_data['title']}' -> "
                                f"'{result.spotify_track.name}' "
                                f"(pop: {result.spotify_track.popularity})"
                            )
                        else:
                            unmatched += 1

                except Exception as e:
                    logger.error(f"Error searching track {track_data['id']}: {e}")
                    errors += 1

                progress.advance(task)
                processed += 1

        logger.info(f"Progress: {matched} matched, {unmatched} unmatched, {errors} errors")
        if progress_callback:
            progress_callback(processed, total, "enriching via Spotify…")

    if progress_callback:
        progress_callback(matched + unmatched + errors, total, "enriching via Spotify…")

    return matched, unmatched, errors


async def run_spotify_enrichment(
    client_id: str,
    client_secret: str,
    batch_size: int = 50,
    limit: int | None = None,
    unattempted_only: bool = False,
    concurrency: int = 1,
    requests_per_second: float = 1.0,
    artist: str | None = None,
    album: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    session_scope: SessionScope | None = None,
) -> EnrichmentStats:
    """Run the Spotify enrichment story line end to end.

    Selects the work queue, estimates runtime, opens one rate-limited Spotify
    client, and streams the queue through ``enrich_tracks`` in committed
    batches. Returns aggregate stats; per-track failures are counted in
    ``errors`` rather than raised.
    """
    logger.info("Starting Spotify enrichment pipeline")
    logger.info(f"Rate limit: {requests_per_second} requests/second")

    # Snapshot the work queue up front; the session closes before any network call.
    with (session_scope or get_session)() as session:
        tracks = get_tracks_to_enrich(
            session,
            limit=limit,
            unattempted_only=unattempted_only,
            artist=artist,
            album=album,
        )

    total = len(tracks)
    if not tracks:
        console.print("[yellow]No tracks to process[/yellow]")
        return EnrichmentStats(total=0, matched=0, unmatched=0, errors=0)

    console.print(f"  Tracks to process: {total:,}")
    estimated_time = total / requests_per_second
    hours = int(estimated_time // 3600)
    minutes = int((estimated_time % 3600) // 60)
    console.print(f"  Estimated time: {hours}h {minutes}m (at {requests_per_second} req/sec)\n")

    completed = [0]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        async with SpotifyClient(
            client_id,
            client_secret,
            concurrency=concurrency,
            requests_per_second=requests_per_second,
        ) as spotify_client:
            matched, unmatched, errors = await enrich_tracks(
                tracks, spotify_client, progress,
                batch_size=max(batch_size, 1),
                progress_callback=progress_callback,
                should_cancel=should_cancel,
                session_scope=session_scope,
            )

            completed[0] = matched + unmatched + errors

    if progress_callback:
        progress_callback(completed[0], total, "enriching via Spotify…")

    logger.info(
        f"Spotify enrichment complete: {matched} matched, "
        f"{unmatched} unmatched, {errors} errors"
    )
    return EnrichmentStats(total=total, matched=matched, unmatched=unmatched, errors=errors)


async def run_listenbrainz_enrichment(
    batch_size: int = 100,
    limit: int | None = None,
    unattempted_only: bool = False,
    requests_per_second: float = 1.0,
    token: str = "",
    artist: str | None = None,
    album: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    session_scope: SessionScope | None = None,
) -> EnrichmentStats:
    """Run the ListenBrainz enrichment story line end to end.

    Selects the MBID-keyed work queue, opens one rate-limited ListenBrainz
    client, and streams the queue through ``enrich_tracks_with_listenbrainz``.
    On completion, raw listen counts are normalized into ``popularity_score``.
    Returns aggregate stats.
    """
    logger.info("Starting ListenBrainz enrichment pipeline")
    logger.info(f"Rate limit: {requests_per_second} requests/second")

    # Snapshot the work queue up front; the session closes before any network call.
    with (session_scope or get_session)() as session:
        tracks = get_tracks_for_listenbrainz(
            session,
            limit=limit,
            unattempted_only=unattempted_only,
            artist=artist,
            album=album,
        )
    total = len(tracks)
    if not tracks:
        console.print("[yellow]No tracks with MusicBrainz recording IDs to process[/yellow]")
        return EnrichmentStats(total=0, matched=0, unmatched=0, errors=0)

    console.print(f"  Tracks with MBIDs to process: {total:,}")
    estimated_batches = math.ceil(total / max(batch_size, 1))
    estimated_time = estimated_batches / requests_per_second
    minutes = int(estimated_time // 60)
    seconds = int(estimated_time % 60)
    console.print(
        f"  Estimated time: {minutes}m {seconds}s "
        f"({estimated_batches:,} batches at {requests_per_second} req/sec)\n"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        async with ListenBrainzClient(
            requests_per_second=requests_per_second, token=token
        ) as listenbrainz_client:
            matched, unmatched, errors = await enrich_tracks_with_listenbrainz(
                tracks,
                listenbrainz_client,
                progress,
                max(batch_size, 1),
                progress_callback=progress_callback,
                should_cancel=should_cancel,
                session_scope=session_scope,
            )

    logger.info(
        f"ListenBrainz enrichment complete: {matched} with popularity, "
        f"{unmatched} without popularity data, {errors} errors"
    )
    return EnrichmentStats(total=total, matched=matched, unmatched=unmatched, errors=errors)


async def run_enrichment(
    source: str = "spotify",
    client_id: str = "",
    client_secret: str = "",
    listenbrainz_token: str = "",
    batch_size: int = 50,
    limit: int | None = None,
    unattempted_only: bool = False,
    concurrency: int = 1,
    requests_per_second: float = 1.0,
    artist: str | None = None,
    album: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    session_scope: SessionScope | None = None,
) -> EnrichmentStats:
    """Dispatch to the selected source's enrichment runner.

    This is the coroutine that ``services.enrichment.enrich_tracks`` wraps with
    ``asyncio.run``. It does no credential checks — the service layer performs
    those — and only routes to ``run_spotify_enrichment`` or
    ``run_listenbrainz_enrichment``.
    """
    if source == "spotify":
        return await run_spotify_enrichment(
            client_id=client_id,
            client_secret=client_secret,
            batch_size=batch_size,
            limit=limit,
            unattempted_only=unattempted_only,
            concurrency=concurrency,
            requests_per_second=requests_per_second,
            artist=artist,
            album=album,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            session_scope=session_scope,
        )
    if source == "listenbrainz":
        return await run_listenbrainz_enrichment(
            batch_size=batch_size,
            limit=limit,
            unattempted_only=unattempted_only,
            requests_per_second=requests_per_second,
            token=listenbrainz_token,
            artist=artist,
            album=album,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            session_scope=session_scope,
        )
    raise ValueError(f"Unknown enrichment source: {source}")
