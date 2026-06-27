"""Enrichment pipeline for batch processing tracks."""

import math
from dataclasses import dataclass

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
from musicseed.enrichers.listenbrainz import ListenBrainzClient
from musicseed.enrichers.spotify import SpotifyClient
from musicseed.logging_config import get_logger

logger = get_logger("enrichers.pipeline")
console = Console()


@dataclass
class EnrichmentStats:
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
    """Get tracks that need Spotify enrichment.

    Args:
        session: Database session
        limit: Max tracks to return
        unattempted_only: Only get tracks not yet attempted

    Returns:
        List of track dicts
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
    """Get tracks with recording MBIDs for ListenBrainz popularity enrichment."""
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

    max_log = math.log10(max_count + 1)
    for track in tracks:
        listen_count = track.listenbrainz_listen_count or 0
        track.popularity_score = math.log10(listen_count + 1) / max_log
        track.popularity_source = "listenbrainz"
    session.commit()


async def enrich_tracks_with_listenbrainz(
    session: Session,
    tracks: list[dict],
    listenbrainz_client: ListenBrainzClient,
    progress: Progress,
    batch_size: int,
) -> tuple[int, int, int]:
    """Enrich tracks with ListenBrainz recording listen/user counts."""
    task = progress.add_task(
        "[cyan]Fetching ListenBrainz popularity...",
        total=len(tracks),
    )

    matched = 0
    unmatched = 0
    errors = 0

    for start in range(0, len(tracks), batch_size):
        batch = tracks[start : start + batch_size]
        mbids = [track["mbid"] for track in batch]
        id_by_mbid = {track["mbid"]: track["id"] for track in batch}

        try:
            results = await listenbrainz_client.get_recording_popularity(mbids)
            for result in results:
                track = session.get(Track, id_by_mbid[result.recording_mbid])
                if track is None:
                    progress.advance(task)
                    continue

                track.listenbrainz_matched = True
                if result.total_listen_count is not None or result.total_user_count is not None:
                    track.listenbrainz_listen_count = result.total_listen_count
                    track.listenbrainz_listener_count = result.total_user_count
                    matched += 1
                else:
                    unmatched += 1
                progress.advance(task)

            session.commit()
        except Exception as e:
            logger.error(f"ListenBrainz batch failed: {e}")
            errors += len(batch)
            progress.advance(task, advance=len(batch))

    normalize_listenbrainz_popularity(session)
    return matched, unmatched, errors


async def enrich_tracks(
    session: Session,
    tracks: list[dict],
    spotify_client: SpotifyClient,
    progress: Progress,
) -> tuple[int, int, int]:
    """Enrich tracks via Spotify search.

    Args:
        session: Database session
        tracks: List of tracks to search
        spotify_client: Spotify client (with throttling)
        progress: Rich progress bar

    Returns:
        Tuple of (matched count, unmatched count, error count)
    """
    task = progress.add_task(
        "[cyan]Searching Spotify (1 req/sec)...",
        total=len(tracks),
    )

    matched = 0
    unmatched = 0
    errors = 0

    for track_data in tracks:
        try:
            result = await spotify_client.match_track(
                title=track_data["title"],
                artist=track_data["artist"],
                album=track_data.get("album"),
                duration_ms=track_data.get("duration_ms"),
            )

            track = session.get(Track, track_data["id"])
            if track:
                track.spotify_matched = True  # Mark as attempted

                if result.matched and result.spotify_track:
                    track.spotify_id = result.spotify_track.spotify_id
                    track.spotify_popularity = result.spotify_track.popularity
                    track.popularity_score = result.spotify_track.popularity / 100
                    track.popularity_source = "spotify"
                    track.match_tier = 2  # Spotify search match
                    matched += 1
                    logger.debug(
                        f"Matched '{track_data['title']}' -> "
                        f"'{result.spotify_track.name}' (pop: {result.spotify_track.popularity})"
                    )
                else:
                    unmatched += 1

        except Exception as e:
            logger.error(f"Error searching track {track_data['id']}: {e}")
            errors += 1

        progress.advance(task)

        # Commit periodically to save progress
        if (matched + unmatched + errors) % 100 == 0:
            session.commit()
            logger.info(f"Progress: {matched} matched, {unmatched} unmatched, {errors} errors")

    session.commit()
    return matched, unmatched, errors


async def run_spotify_enrichment(
    session: Session,
    client_id: str,
    client_secret: str,
    batch_size: int = 50,
    limit: int | None = None,
    unattempted_only: bool = False,
    concurrency: int = 1,
    requests_per_second: float = 1.0,
    artist: str | None = None,
    album: str | None = None,
) -> EnrichmentStats:
    """Run the enrichment pipeline via Spotify search."""
    logger.info("Starting Spotify enrichment pipeline")
    logger.info(f"Rate limit: {requests_per_second} requests/second")

    tracks = get_tracks_to_enrich(
        session,
        limit=limit,
        unattempted_only=unattempted_only,
        artist=artist,
        album=album,
    )

    if not tracks:
        console.print("[yellow]No tracks to process[/yellow]")
        return EnrichmentStats(total=0, matched=0, unmatched=0, errors=0)

    console.print(f"  Tracks to process: {len(tracks):,}")
    estimated_time = len(tracks) / requests_per_second
    hours = int(estimated_time // 3600)
    minutes = int((estimated_time % 3600) // 60)
    console.print(f"  Estimated time: {hours}h {minutes}m (at {requests_per_second} req/sec)\n")

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
                session, tracks, spotify_client, progress
            )

    logger.info(
        f"Spotify enrichment complete: {matched} matched, "
        f"{unmatched} unmatched, {errors} errors"
    )
    return EnrichmentStats(len(tracks), matched, unmatched, errors)


async def run_listenbrainz_enrichment(
    session: Session,
    batch_size: int = 100,
    limit: int | None = None,
    unattempted_only: bool = False,
    requests_per_second: float = 1.0,
    artist: str | None = None,
    album: str | None = None,
) -> EnrichmentStats:
    """Run ListenBrainz popularity enrichment for tracks with MBIDs."""
    logger.info("Starting ListenBrainz enrichment pipeline")
    logger.info(f"Rate limit: {requests_per_second} requests/second")

    tracks = get_tracks_for_listenbrainz(
        session,
        limit=limit,
        unattempted_only=unattempted_only,
        artist=artist,
        album=album,
    )
    if not tracks:
        console.print("[yellow]No tracks with MusicBrainz recording IDs to process[/yellow]")
        return EnrichmentStats(total=0, matched=0, unmatched=0, errors=0)

    console.print(f"  Tracks with MBIDs to process: {len(tracks):,}")
    estimated_batches = math.ceil(len(tracks) / max(batch_size, 1))
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
            requests_per_second=requests_per_second
        ) as listenbrainz_client:
            matched, unmatched, errors = await enrich_tracks_with_listenbrainz(
                session,
                tracks,
                listenbrainz_client,
                progress,
                max(batch_size, 1),
            )

    logger.info(
        f"ListenBrainz enrichment complete: {matched} with popularity, "
        f"{unmatched} without popularity data, {errors} errors"
    )
    return EnrichmentStats(len(tracks), matched, unmatched, errors)


async def run_enrichment(
    session: Session,
    source: str = "spotify",
    client_id: str = "",
    client_secret: str = "",
    batch_size: int = 50,
    limit: int | None = None,
    unattempted_only: bool = False,
    concurrency: int = 1,
    requests_per_second: float = 1.0,
    artist: str | None = None,
    album: str | None = None,
) -> EnrichmentStats:
    """Run enrichment for the selected source."""
    if source == "spotify":
        return await run_spotify_enrichment(
            session=session,
            client_id=client_id,
            client_secret=client_secret,
            batch_size=batch_size,
            limit=limit,
            unattempted_only=unattempted_only,
            concurrency=concurrency,
            requests_per_second=requests_per_second,
            artist=artist,
            album=album,
        )
    if source == "listenbrainz":
        return await run_listenbrainz_enrichment(
            session=session,
            batch_size=batch_size,
            limit=limit,
            unattempted_only=unattempted_only,
            requests_per_second=requests_per_second,
            artist=artist,
            album=album,
        )
    raise ValueError(f"Unknown enrichment source: {source}")
