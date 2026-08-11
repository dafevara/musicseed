"""Plex sonic analysis service — inspect and trigger Plex's own sonic analysis.

Keeps the Plex sonic vectors that MusicSeed reads at query time (see
``musicseed.sonic``) up to date:

1. Which tracks has Plex already analyzed sonically (``musicAnalysisVersion``)?
2. Trigger the ``MusicAnalysis`` Butler task on demand (``POST /butler/…``) and
   watch a date-scoped window of recently added music until it is analyzed.

Note: the Butler task always processes Plex's *entire* pending backlog; the
date window scopes what we target, watch, and report — not what Plex runs.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from pydantic import BaseModel

from musicseed.clients.plex import LibrarySectionResult, MediaItem, PlexClient
from musicseed.config import get_config
from musicseed.exceptions import ConfigurationError, NotFoundError

BUTLER_SONIC_TASK = "MusicAnalysis"


class UnanalyzedAlbum(BaseModel):
    """An album that has at least one track without Plex sonic analysis."""

    model_config = {"frozen": True}

    rating_key: str
    title: str | None
    artist: str | None
    track_count: int
    unanalyzed_count: int
    most_recent_added_at: datetime | None


class SonicStatusResult(BaseModel):
    """Sonic analysis coverage of a Plex music library."""

    model_config = {"frozen": True}

    library_name: str
    section_id: str
    total_tracks: int
    analyzed_tracks: int
    recent_days: int
    recent_tracks: int
    recent_analyzed_tracks: int
    unanalyzed_albums: list[UnanalyzedAlbum]

    @property
    def unanalyzed_tracks(self) -> int:
        return self.total_tracks - self.analyzed_tracks

    @property
    def recent_unanalyzed_tracks(self) -> int:
        return self.recent_tracks - self.recent_analyzed_tracks


class SonicTriggerProbeResult(BaseModel):
    """Outcome of triggering Plex analysis on one album and re-checking it."""

    model_config = {"frozen": True}

    trigger_method: str
    album_rating_key: str
    album_title: str | None
    artist_title: str | None
    track_count: int
    analyzed_before: int
    analyzed_after: int
    waited_seconds: float
    activities_observed: list[str]

    @property
    def sonic_triggered(self) -> bool:
        return self.analyzed_after > self.analyzed_before


class SonicRefreshResult(BaseModel):
    """Outcome of a date-scoped sonic analysis refresh."""

    model_config = {"frozen": True}

    library_name: str
    days: int
    pending_tracks_before: int
    pending_tracks_after: int
    pending_albums_before: list[UnanalyzedAlbum]
    still_pending_albums: list[UnanalyzedAlbum]
    activities_observed: list[str]
    waited_seconds: float
    stall_detected: bool

    @property
    def analyzed_delta(self) -> int:
        return self.pending_tracks_before - self.pending_tracks_after

    @property
    def completed(self) -> bool:
        return self.pending_tracks_after == 0


def _plex_client(timeout: float = 120.0) -> PlexClient:
    config = get_config()
    if not config.plex.token:
        raise ConfigurationError(
            "plex.token is not configured. Add it to your config file."
        )
    return PlexClient(base_url=config.plex.url, token=config.plex.token, timeout=timeout)


def _resolve_music_section(
    client: PlexClient, library_name: str
) -> LibrarySectionResult:
    """Resolve a library name to its music section (HTTP section id).

    Raises NotFoundError if no music section with that name exists.
    """
    sections = client.list_library_sections()
    music = [s for s in sections if s.type == "artist"]
    for section in music:
        if section.title == library_name:
            return section
    for section in music:
        if section.title.lower() == library_name.lower():
            return section
    names = ", ".join(s.title for s in music) or "none"
    raise NotFoundError(
        f"No Plex music library named '{library_name}' was found. "
        f"Available music libraries: {names}."
    )


def _unanalyzed_albums(tracks: list[MediaItem]) -> list[UnanalyzedAlbum]:
    """Group tracks by album and keep those with unanalyzed tracks, most recent first."""
    by_album: dict[str, list[MediaItem]] = {}
    for track in tracks:
        if track.parent_rating_key:
            by_album.setdefault(track.parent_rating_key, []).append(track)

    albums = []
    for album_key, album_tracks in by_album.items():
        unanalyzed = [t for t in album_tracks if not t.has_sonic_analysis]
        if not unanalyzed:
            continue
        first = album_tracks[0]
        added = [t.added_at for t in album_tracks if t.added_at is not None]
        albums.append(
            UnanalyzedAlbum(
                rating_key=album_key,
                title=first.parent_title,
                artist=first.grandparent_title,
                track_count=len(album_tracks),
                unanalyzed_count=len(unanalyzed),
                most_recent_added_at=max(added) if added else None,
            )
        )
    albums.sort(
        key=lambda a: a.most_recent_added_at or datetime.min, reverse=True
    )
    return albums


def get_sonic_status(
    library_name: str | None = None,
    *,
    recent_days: int = 7,
) -> SonicStatusResult:
    """Report Plex sonic analysis coverage for a music library.

    Fetches every track in the library over the HTTP API, so it can be slow on
    large libraries. ``recent_days`` defines the "recent additions" window
    (based on Plex's ``addedAt``).

    Raises:
        ConfigurationError: if plex.token is not configured.
        NotFoundError: if the library name doesn't match a music section.
        PlexAPIError: if the Plex API call fails.
    """
    config = get_config()
    target_library = library_name or config.plex.library
    client = _plex_client()
    section = _resolve_music_section(client, target_library)
    tracks = client.get_section_tracks(section.key)

    cutoff = datetime.now() - timedelta(days=recent_days)
    recent = [t for t in tracks if t.added_at is not None and t.added_at >= cutoff]

    return SonicStatusResult(
        library_name=section.title,
        section_id=section.key,
        total_tracks=len(tracks),
        analyzed_tracks=sum(t.has_sonic_analysis for t in tracks),
        recent_days=recent_days,
        recent_tracks=len(recent),
        recent_analyzed_tracks=sum(t.has_sonic_analysis for t in recent),
        unanalyzed_albums=_unanalyzed_albums(tracks),
    )


def _pick_probe_album(
    album_rating_key: str | None, library_name: str | None
) -> str:
    """Resolve the album to watch: the given key, or the most recent unanalyzed one."""
    if album_rating_key is not None:
        return album_rating_key
    status = get_sonic_status(library_name)
    if not status.unanalyzed_albums:
        raise NotFoundError(
            f"Every album in library '{status.library_name}' already has "
            "sonic analysis. Nothing to probe."
        )
    return status.unanalyzed_albums[0].rating_key


def _watch_album(
    client: PlexClient,
    album_rating_key: str,
    analyzed_before: int,
    wait_seconds: float,
    poll_interval: float,
) -> tuple[int, list[str], float]:
    """Poll an album until sonic analysis appears or the wait budget runs out."""
    activities_observed: list[str] = []
    analyzed_after = analyzed_before
    deadline = time.monotonic() + wait_seconds
    while True:
        time.sleep(poll_interval)
        for activity in client.get_activities():
            label = f"{activity.title} — {activity.subtitle}".strip(" —")
            if label not in activities_observed:
                activities_observed.append(label)
        after = client.get_album_tracks(album_rating_key)
        analyzed_after = sum(t.has_sonic_analysis for t in after)
        if analyzed_after > analyzed_before or time.monotonic() >= deadline:
            break
    waited = wait_seconds - max(0.0, deadline - time.monotonic())
    return analyzed_after, activities_observed, waited


def _run_trigger_probe(
    client: PlexClient,
    album_rating_key: str,
    trigger_method: str,
    trigger: Callable[[], None],
    wait_seconds: float,
    poll_interval: float,
) -> SonicTriggerProbeResult:
    before = client.get_album_tracks(album_rating_key)
    if not before:
        raise NotFoundError(
            f"No tracks found for Plex album ratingKey={album_rating_key}."
        )
    analyzed_before = sum(t.has_sonic_analysis for t in before)

    trigger()

    analyzed_after, activities_observed, waited = _watch_album(
        client, album_rating_key, analyzed_before, wait_seconds, poll_interval
    )
    return SonicTriggerProbeResult(
        trigger_method=trigger_method,
        album_rating_key=album_rating_key,
        album_title=before[0].parent_title,
        artist_title=before[0].grandparent_title,
        track_count=len(before),
        analyzed_before=analyzed_before,
        analyzed_after=analyzed_after,
        waited_seconds=waited,
        activities_observed=activities_observed,
    )


def refresh_album(album_rating_key: str) -> None:
    """Ask Plex to refresh one album's metadata (re-reads its files from disk).

    This recreates the album's media items, which clears the failed-analysis
    state that prevents sonic analysis from being queued.

    Raises:
        ConfigurationError: if plex.token is not configured.
        PlexAPIError: if the Plex API call fails.
    """
    client = _plex_client(timeout=30.0)
    client.refresh_item(album_rating_key)


def probe_sonic_trigger(
    album_rating_key: str | None = None,
    library_name: str | None = None,
    *,
    wait_seconds: float = 120.0,
    poll_interval: float = 5.0,
) -> SonicTriggerProbeResult:
    """Trigger Plex analysis on one album and check if sonic analysis follows.

    If ``album_rating_key`` is None, the most recently added album with
    unanalyzed tracks is picked automatically. Polls the album's tracks until
    the number of sonically analyzed tracks increases or ``wait_seconds``
    elapses.

    Raises:
        ConfigurationError: if plex.token is not configured.
        NotFoundError: if no unanalyzed album can be found.
        PlexAPIError: if the Plex API call fails.
    """
    client = _plex_client()
    album_rating_key = _pick_probe_album(album_rating_key, library_name)
    return _run_trigger_probe(
        client,
        album_rating_key,
        "analyze",
        lambda: client.analyze_item(album_rating_key),
        wait_seconds,
        poll_interval,
    )


def probe_butler_trigger(
    album_rating_key: str | None = None,
    library_name: str | None = None,
    *,
    butler_task: str = "MusicAnalysis",
    wait_seconds: float = 120.0,
    poll_interval: float = 5.0,
) -> SonicTriggerProbeResult:
    """Trigger a Plex Butler task and check if sonic analysis follows.

    Unlike per-item ``analyze``, the ``MusicAnalysis`` Butler task works
    through every album pending sonic analysis on the server, which can be
    CPU-heavy and long-running — it keeps going after this probe returns.

    Raises:
        ConfigurationError: if plex.token is not configured.
        NotFoundError: if no unanalyzed album can be found.
        PlexAPIError: if the Plex API call fails.
    """
    client = _plex_client()
    album_rating_key = _pick_probe_album(album_rating_key, library_name)
    return _run_trigger_probe(
        client,
        album_rating_key,
        f"butler:{butler_task}",
        lambda: client.run_butler_task(butler_task),
        wait_seconds,
        poll_interval,
    )


def _window_albums(status: SonicStatusResult, days: int) -> list[UnanalyzedAlbum]:
    """Unanalyzed albums whose most recent track was added within the window."""
    cutoff = datetime.now() - timedelta(days=days)
    return [
        album
        for album in status.unanalyzed_albums
        if album.most_recent_added_at is not None
        and album.most_recent_added_at >= cutoff
    ]


def refresh_sonic_analysis(
    library_name: str | None = None,
    *,
    days: int = 7,
    wait_seconds: float = 900.0,
    poll_interval: float = 15.0,
    stall_after: int = 4,
    on_poll: Callable[[int, int], None] | None = None,
) -> SonicRefreshResult:
    """Refresh sonic analysis for music added in the last ``days`` days.

    Triggers the Plex ``MusicAnalysis`` Butler task and watches the window's
    pending track count until it reaches zero, stalls (no progress across
    ``stall_after`` consecutive polls), or ``wait_seconds`` elapses. The Butler
    task keeps running on the server after this function returns.

    ``on_poll(pending_now, pending_before)`` is called after each poll so a
    surface can render progress.

    Raises:
        ConfigurationError: if plex.token is not configured.
        NotFoundError: if the library name doesn't match a music section.
        PlexAPIError: if the Plex API call fails.
    """
    client = _plex_client()
    before = get_sonic_status(library_name, recent_days=days)
    pending_before = before.recent_unanalyzed_tracks

    if pending_before == 0:
        return SonicRefreshResult(
            library_name=before.library_name,
            days=days,
            pending_tracks_before=0,
            pending_tracks_after=0,
            pending_albums_before=[],
            still_pending_albums=[],
            activities_observed=[],
            waited_seconds=0.0,
            stall_detected=False,
        )

    client.run_butler_task(BUTLER_SONIC_TASK)

    activities_observed: list[str] = []
    pending_now = pending_before
    last_status = before
    stalls = 0
    deadline = time.monotonic() + wait_seconds
    start = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        for activity in client.get_activities():
            label = f"{activity.title} — {activity.subtitle}".strip(" —")
            if label not in activities_observed:
                activities_observed.append(label)
        last_status = get_sonic_status(library_name, recent_days=days)
        previous = pending_now
        pending_now = last_status.recent_unanalyzed_tracks
        stalls = stalls + 1 if pending_now >= previous else 0
        if on_poll is not None:
            on_poll(pending_now, pending_before)
        if pending_now == 0 or stalls >= stall_after:
            break

    return SonicRefreshResult(
        library_name=last_status.library_name,
        days=days,
        pending_tracks_before=pending_before,
        pending_tracks_after=pending_now,
        pending_albums_before=_window_albums(before, days),
        still_pending_albums=_window_albums(last_status, days),
        activities_observed=activities_observed,
        waited_seconds=time.monotonic() - start,
        stall_detected=stalls >= stall_after and pending_now > 0,
    )

