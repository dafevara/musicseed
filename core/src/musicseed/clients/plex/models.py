"""Pydantic models for Plex Media Server API responses.

Aligned with the Plex Media Server OpenAPI spec (v0.2.0) schemas from
https://plexapi.dev. Every model notes its corresponding spec schema where
one exists. Fields that MusicSeed does not use yet are included as Optional
so callers can access them without waiting for a code change.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Connection / diagnostic (MusicSeed-specific — no spec equivalent)
# ---------------------------------------------------------------------------


class ConnectionCheck(BaseModel):
    """Result of probing the Plex server root endpoint (never raises).

    ``error`` is a safe diagnostic string — it never contains the token.
    """

    model_config = {"frozen": True}

    reachable: bool
    authorized: bool
    status_code: int | None
    server_version: str | None
    error: str | None


# ---------------------------------------------------------------------------
# Spec: Activity (no dedicated spec schema — the /activities endpoint is
# undocumented but widely used)
# ---------------------------------------------------------------------------


class ActivityInfo(BaseModel):
    """A running server activity (Butler task, analysis, etc.)."""

    model_config = {"frozen": True}

    type: str
    title: str
    subtitle: str
    progress: int | None


# ---------------------------------------------------------------------------
# Spec: LibrarySection, LibrarySections
# ---------------------------------------------------------------------------


class LibrarySectionResult(BaseModel):
    """A Plex library section.  Spec: ``LibrarySection``."""

    model_config = {"frozen": True}

    key: str
    title: str
    type: str


# ---------------------------------------------------------------------------
# Spec: Tag
# ---------------------------------------------------------------------------


class Tag(BaseModel):
    """A generic tag (genre, mood, director, country, etc.).
    Spec: ``Tag``.
    """

    model_config = {"frozen": True}

    tag: str
    id: int | None = None


# ---------------------------------------------------------------------------
# Spec: Media, Part
# ---------------------------------------------------------------------------


class Part(BaseModel):
    """A media part (one file within a media version).  Spec: ``Part``."""

    model_config = {"frozen": True}

    id: int
    key: str | None = None
    duration: int | None = None
    file: str | None = None
    size: int | None = None
    container: str | None = None


class Media(BaseModel):
    """A media version of a library item (audio or video stream info).
    Spec: ``Media``.
    """

    model_config = {"frozen": True}

    id: int
    duration: int | None = None
    bitrate: int | None = None
    audio_channels: int | None = None
    audio_codec: str | None = None
    video_codec: str | None = None
    video_resolution: str | None = None
    container: str | None = None
    video_frame_rate: str | None = None
    parts: list[Part] = []


# ---------------------------------------------------------------------------
# Spec: MediaItem — the core model for tracks, albums, artists, etc.
# ---------------------------------------------------------------------------


class MediaItem(BaseModel):
    """A library metadata item (track, album, artist, photo, etc.).

    Spec: ``MediaItem``.  This is the richest model in the spec and covers
    every metadata endpoint.  Fields that Plex omits for a given media type
    are returned as ``None``.

    Three fields are *not* in the spec but appear in real Plex responses:
    ``parent_title`` and ``grandparent_title`` are denormalised convenience
    keys in ``/library/sections/{key}/all`` and
    ``/library/metadata/{key}/children``; ``has_sonic_analysis`` is derived
    from the presence of ``musicAnalysisVersion`` in the same endpoints.
    """

    model_config = {"frozen": True}

    # -- identity -----------------------------------------------------------
    rating_key: str
    key: str | None = None
    parent_rating_key: str | None = None
    grandparent_rating_key: str | None = None
    guid: str | None = None
    parent_guid: str | None = None
    grandparent_guid: str | None = None
    type: str | None = None  # "track", "album", "artist", "photo", etc.

    # -- textual ------------------------------------------------------------
    title: str = ""
    title_sort: str | None = None
    summary: str | None = None
    tagline: str | None = None

    # -- denormalised parent names (non-spec, from section/children endpoints)
    parent_title: str | None = None
    grandparent_title: str | None = None

    # -- temporal -----------------------------------------------------------
    duration: int | None = None
    added_at: datetime | None = None
    updated_at: datetime | None = None
    originally_available_at: str | None = None
    last_viewed_at: datetime | None = None
    view_count: int | None = None

    # -- music-specific (present on track/album responses) ------------------
    year: int | None = None
    studio: str | None = None
    content_rating: str | None = None
    rating: float | None = None
    user_rating: float | None = None

    # -- artwork ------------------------------------------------------------
    thumb: str | None = None
    art: str | None = None
    banner: str | None = None
    theme: str | None = None

    # -- children -----------------------------------------------------------
    media: list[Media] = []
    genres: list[Tag] = []
    directors: list[Tag] = []
    writers: list[Tag] = []
    roles: list[Tag] = []

    # -- sonic analysis (non-spec, from musicAnalysisVersion presence) ------
    has_sonic_analysis: bool = False


# ---------------------------------------------------------------------------
# Spec: Playlist, Playlists
# ---------------------------------------------------------------------------


class Playlist(BaseModel):
    """A Plex playlist.  Spec: ``Playlist``."""

    model_config = {"frozen": True}

    rating_key: str
    key: str | None = None
    title: str
    type: str | None = None
    playlist_type: str | None = None
    summary: str | None = None
    smart: bool = False
    leaf_count: int | None = None
    added_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Spec: Hub, HubEntry — search / discovery endpoints
# ---------------------------------------------------------------------------


class HubEntry(BaseModel):
    """A single result row inside a hub.  Spec: ``HubEntry``."""

    model_config = {"frozen": True}

    key: str
    title: str
    type: str
    hub_identifier: str | None = None
    context: str | None = None
    size: int | None = None
    items: list[MediaItem] = []  # spec: Metadata[]
    more: bool = False


class HubResult(BaseModel):
    """One search / discovery hub.  Spec: ``Hub``."""

    model_config = {"frozen": True}

    size: int | None = None
    identifier: str | None = None
    title: str | None = None
    entries: list[HubEntry] = []
    more: bool = False
