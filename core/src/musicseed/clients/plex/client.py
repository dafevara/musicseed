"""Plex Media Server HTTP API client — transport, auth, and endpoint methods.

Mapping to the Plex OpenAPI spec (v0.2.0, https://plexapi.dev):
    - Spec tag "Server"      → server info, identity, preferences
    - Spec tag "Library"     → library sections, section contents
    - Spec tag "Metadata"    → single-item metadata, children, similar, analyze, refresh
    - Spec tag "Playlists"   → playlist CRUD
    - Spec tag "Hub"         → search, home, promoted
    - Spec tag "Sessions"    → active sessions, history (future)
    - Spec tag "Media"       → photo/video transcode, timeline (future)

Every public method includes the spec path so the contract can be verified
against the machine-readable spec at any time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.etree import ElementTree

import httpx

from musicseed.clients.plex.models import (
    ActivityInfo,
    ConnectionCheck,
    HubEntry,
    HubResult,
    LibrarySectionResult,
    Media,
    MediaItem,
    Part,
    Playlist,
    Tag,
)


class PlexAPIError(RuntimeError):
    """Raised for Plex API errors that should be surfaced to the user."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_epoch(value: int | float | None) -> datetime | None:
    """Convert a Plex epoch timestamp (int seconds) to a datetime."""
    if value is None:
        return None
    return datetime.fromtimestamp(value)


def _parse_media_item(raw: dict[str, Any]) -> MediaItem:
    """Parse a raw dict from Plex JSON into a MediaItem.

    Covers the spec ``MediaItem`` schema.  Unknown / future keys are ignored.
    """
    return MediaItem(
        rating_key=str(raw.get("ratingKey", "")),
        key=raw.get("key"),
        parent_rating_key=_str_or_none(raw.get("parentRatingKey")),
        grandparent_rating_key=_str_or_none(raw.get("grandparentRatingKey")),
        guid=raw.get("guid"),
        parent_guid=raw.get("parentGuid"),
        grandparent_guid=raw.get("grandparentGuid"),
        type=raw.get("type"),
        title=raw.get("title", ""),
        title_sort=raw.get("titleSort"),
        summary=raw.get("summary"),
        tagline=raw.get("tagline"),
        parent_title=raw.get("parentTitle"),
        grandparent_title=raw.get("grandparentTitle"),
        duration=raw.get("duration"),
        added_at=_parse_epoch(raw.get("addedAt")),
        updated_at=_parse_epoch(raw.get("updatedAt")),
        originally_available_at=raw.get("originallyAvailableAt"),
        last_viewed_at=_parse_epoch(raw.get("lastViewedAt")),
        view_count=raw.get("viewCount"),
        year=raw.get("year"),
        studio=raw.get("studio"),
        content_rating=raw.get("contentRating"),
        rating=raw.get("rating"),
        user_rating=raw.get("userRating"),
        thumb=raw.get("thumb"),
        art=raw.get("art"),
        banner=raw.get("banner"),
        theme=raw.get("theme"),
        media=[_parse_media(m) for m in raw.get("Media", []) or []],
        genres=[Tag(tag=g["tag"], id=g.get("id")) for g in raw.get("Genre", []) or []],
        directors=[Tag(tag=d["tag"], id=d.get("id")) for d in raw.get("Director", []) or []],
        writers=[Tag(tag=w["tag"], id=w.get("id")) for w in raw.get("Writer", []) or []],
        roles=[Tag(tag=r["tag"], id=r.get("id")) for r in raw.get("Role", []) or []],
        has_sonic_analysis="musicAnalysisVersion" in raw,
    )


def _parse_media(raw: dict[str, Any]) -> Media:
    """Parse a raw dict into a Media object (spec: ``Media``)."""
    return Media(
        id=raw.get("id", 0),
        duration=raw.get("duration"),
        bitrate=raw.get("bitrate"),
        audio_channels=raw.get("audioChannels"),
        audio_codec=raw.get("audioCodec"),
        video_codec=raw.get("videoCodec"),
        video_resolution=raw.get("videoResolution"),
        container=raw.get("container"),
        video_frame_rate=raw.get("videoFrameRate"),
        parts=[_parse_part(p) for p in raw.get("Part", []) or []],
    )


def _parse_part(raw: dict[str, Any]) -> Part:
    """Parse a raw dict into a Part object (spec: ``Part``)."""
    return Part(
        id=raw.get("id", 0),
        key=raw.get("key"),
        duration=raw.get("duration"),
        file=raw.get("file"),
        size=raw.get("size"),
        container=raw.get("container"),
    )


def _str_or_none(value: Any) -> str | None:
    """Return ``str(value)`` or None if *value* is None/falsy."""
    return str(value) if value else None


# ---------------------------------------------------------------------------
# PlexClient
# ---------------------------------------------------------------------------


class PlexClient:
    """Synchronous HTTP client for Plex Media Server.

    Every endpoint method maps to a documented Plex API path.  The spec
    reference (e.g. ``Spec: GET /library/sections``) links back to the
    OpenAPI contract at https://plexapi.dev.
    """

    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {
            "X-Plex-Token": token,
            "Accept": "application/json",
        }
        self._timeout = timeout

    # -- low-level HTTP ------------------------------------------------------

    def _send(self, method: str, path: str, **params: Any) -> httpx.Response:
        """Issue an HTTP request and raise ``PlexAPIError`` on failure."""
        try:
            resp = httpx.request(
                method,
                f"{self._base}{path}",
                headers=self._headers,
                params=params or None,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp
        except httpx.ConnectError as e:
            raise PlexAPIError(
                f"Cannot reach Plex at {self._base}. Is Plex Media Server running?"
            ) from e
        except httpx.HTTPStatusError as e:
            raise PlexAPIError(
                f"Plex returned HTTP {e.response.status_code} for {method} {path}. "
                "Check your plex.token in config."
            ) from e

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        return self._send("GET", path, **params).json()

    def _post(self, path: str, **params: Any) -> dict[str, Any]:
        return self._send("POST", path, **params).json()

    def _put(self, path: str, **params: Any) -> dict[str, Any]:
        resp = self._send("PUT", path, **params)
        return resp.json() if resp.content else {}

    # -- server (spec: Server) -----------------------------------------------

    def check_connection(self) -> ConnectionCheck:
        """Probe ``GET /`` without raising; used by setup/discovery flows.

        Spec: ``GET /`` — Get server information.
        """
        try:
            resp = httpx.get(
                f"{self._base}/", headers=self._headers, timeout=self._timeout
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            return ConnectionCheck(
                reachable=False,
                authorized=False,
                status_code=None,
                server_version=None,
                error=(
                    f"Cannot reach Plex at {self._base} ({type(e).__name__}). "
                    "Is Plex Media Server running?"
                ),
            )
        except httpx.HTTPError as e:
            return ConnectionCheck(
                reachable=False,
                authorized=False,
                status_code=None,
                server_version=None,
                error=f"HTTP error contacting Plex at {self._base}: {e}",
            )

        version = None
        if resp.status_code == 200:
            try:
                version = resp.json().get("MediaContainer", {}).get("version")
            except ValueError:
                pass
        return ConnectionCheck(
            reachable=True,
            authorized=resp.status_code not in (401, 403),
            status_code=resp.status_code,
            server_version=version,
            error=None if resp.status_code == 200 else f"Plex returned HTTP {resp.status_code}.",
        )

    def machine_identifier(self) -> str:
        """Return the server machine identifier (needed to build track URIs).

        Spec: ``GET /`` — ``MediaContainer.machineIdentifier``.
        """
        data = self._get("/")
        return data["MediaContainer"]["machineIdentifier"]

    # -- library (spec: Library) ---------------------------------------------

    def list_library_sections(self) -> list[LibrarySectionResult]:
        """Return every library section on the server.

        Spec: ``GET /library/sections``.
        """
        data = self._get("/library/sections")
        items = data.get("MediaContainer", {}).get("Directory") or []
        return [
            LibrarySectionResult(
                key=str(item["key"]),
                title=item["title"],
                type=item.get("type", ""),
            )
            for item in items
        ]

    def get_section_tracks(self, section_id: str) -> list[MediaItem]:
        """Return every track in a library section.

        Spec: ``GET /library/sections/{sectionKey}/all`` — type=10 (tracks).
        Can be slow on large libraries.
        """
        data = self._get(f"/library/sections/{section_id}/all", type="10")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [_parse_media_item(item) for item in items]

    def get_recently_added(
        self, section_id: str | None = None
    ) -> list[MediaItem]:
        """Return recently added items, optionally scoped to a section.

        Spec: ``GET /library/recentlyAdded`` or
        ``GET /library/sections/{sectionKey}/recentlyAdded``.
        """
        if section_id:
            path = f"/library/sections/{section_id}/recentlyAdded"
        else:
            path = "/library/recentlyAdded"
        data = self._get(path)
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [_parse_media_item(item) for item in items]

    # -- metadata (spec: Metadata) -------------------------------------------

    def get_metadata(self, rating_key: str) -> MediaItem | None:
        """Return metadata for a single library item.

        Spec: ``GET /library/metadata/{ratingKey}``.
        """
        data = self._get(f"/library/metadata/{rating_key}")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return _parse_media_item(items[0]) if items else None

    def get_metadata_children(self, rating_key: str) -> list[MediaItem]:
        """Return the children of an album, artist, season, etc.

        Spec: ``GET /library/metadata/{ratingKey}/children``.
        """
        data = self._get(f"/library/metadata/{rating_key}/children")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [_parse_media_item(item) for item in items]

    def get_album_tracks(self, album_rating_key: str) -> list[MediaItem]:
        """Return the tracks of a single album by its ratingKey.

        Spec: ``GET /library/metadata/{ratingKey}/children`` (album children).
        """
        data = self._get(f"/library/metadata/{album_rating_key}/children")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [_parse_media_item(item) for item in items]

    def get_similar(self, rating_key: str) -> list[MediaItem]:
        """Return items similar to the given one.

        Spec: ``GET /library/metadata/{ratingKey}/similar``.
        """
        data = self._get(f"/library/metadata/{rating_key}/similar")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [_parse_media_item(item) for item in items]

    def analyze_item(self, rating_key: str) -> None:
        """Queue Plex analysis (sonic, loudness, etc.) for a single item.

        Spec: ``PUT /library/metadata/{ratingKey}/analyze`` (undocumented
        endpoint but widely used).
        """
        self._put(f"/library/metadata/{rating_key}/analyze")

    def refresh_item(self, rating_key: str) -> None:
        """Refresh metadata for a single item (re-reads its files from disk).

        Spec: ``PUT /library/metadata/{ratingKey}/refresh`` (undocumented
        endpoint but widely used).
        """
        self._put(f"/library/metadata/{rating_key}/refresh")

    # -- playlists (spec: Playlists) -----------------------------------------

    def find_playlist(self, name: str) -> Playlist | None:
        """Return the playlist with this exact name, or None.

        Spec: ``GET /playlists`` — filtered to playlistType=audio.
        """
        data = self._get("/playlists", playlistType="audio")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        for item in items:
            if item.get("title") == name:
                return Playlist(
                    rating_key=str(item["ratingKey"]),
                    key=item.get("key"),
                    title=item["title"],
                    type=item.get("type"),
                    playlist_type=item.get("playlistType"),
                    summary=item.get("summary"),
                    smart=item.get("smart", False),
                    leaf_count=item.get("leafCount"),
                    added_at=_parse_epoch(item.get("addedAt")),
                    updated_at=_parse_epoch(item.get("updatedAt")),
                )
        return None

    def get_playlist(self, rating_key: str) -> Playlist | None:
        """Return the audio playlist with this ratingKey, or None."""
        key = str(rating_key)
        for playlist in self.list_playlists():
            if playlist.rating_key == key:
                return playlist
        return None

    def list_playlists(self) -> list[Playlist]:
        """Return every audio playlist on the server.

        Spec: ``GET /playlists``.
        """
        data = self._get("/playlists", playlistType="audio")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [
            Playlist(
                rating_key=str(item["ratingKey"]),
                key=item.get("key"),
                title=item["title"],
                type=item.get("type"),
                playlist_type=item.get("playlistType"),
                summary=item.get("summary"),
                smart=item.get("smart", False),
                leaf_count=item.get("leafCount"),
                added_at=_parse_epoch(item.get("addedAt")),
                updated_at=_parse_epoch(item.get("updatedAt")),
            )
            for item in items
        ]

    def get_playlist_tracks(self, rating_key: str) -> list[MediaItem]:
        """Return every track currently in a playlist.

        Spec: ``GET /playlists/{playlistKey}/items``.
        """
        data = self._get(f"/playlists/{rating_key}/items")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [_parse_media_item(item) for item in items]

    def _metadata_uri(self, plex_ids: list[int]) -> str:
        """Build a ``server://…/library/metadata/…`` URI for playlist ops."""
        machine_id = self.machine_identifier()
        ids_str = ",".join(str(pid) for pid in plex_ids)
        return (
            f"server://{machine_id}/com.plexapp.plugins.library"
            f"/library/metadata/{ids_str}"
        )

    def create_playlist(self, name: str, plex_ids: list[int]) -> Playlist:
        """Create an audio playlist from a list of Plex track ratingKeys.

        Spec: ``POST /playlists``.

        Raises ``PlexAPIError`` if the name already exists or the id list is empty.
        """
        if not plex_ids:
            raise PlexAPIError(
                f"Cannot create playlist '{name}': none of the recommended tracks "
                "have a Plex ID in the database."
            )

        existing = self.find_playlist(name)
        if existing is not None:
            raise PlexAPIError(
                f"A playlist named '{name}' already exists in Plex "
                f"(id={existing.rating_key}). "
                "Choose a different name with --name."
            )

        data = self._post(
            "/playlists",
            title=name,
            type="audio",
            smart="0",
            uri=self._metadata_uri(plex_ids),
        )
        item = data["MediaContainer"]["Metadata"][0]
        return Playlist(
            rating_key=str(item["ratingKey"]),
            key=item.get("key"),
            title=item["title"],
            type=item.get("type"),
            playlist_type=item.get("playlistType"),
            summary=item.get("summary"),
            smart=item.get("smart", False),
            leaf_count=item.get("leafCount"),
            added_at=_parse_epoch(item.get("addedAt")),
            updated_at=_parse_epoch(item.get("updatedAt")),
        )

    def add_to_playlist(self, rating_key: str, plex_ids: list[int]) -> None:
        """Add tracks to an existing playlist by Plex track ratingKeys.

        Spec: ``POST /playlists/{playlistKey}/items``.

        Raises ``PlexAPIError`` if the id list is empty.
        """
        if not plex_ids:
            raise PlexAPIError(
                f"Cannot add tracks to playlist (id={rating_key}): none of the "
                "recommended tracks have a Plex ID in the database."
            )

        self._put(
            f"/playlists/{rating_key}/items",
            uri=self._metadata_uri(plex_ids),
        )

    def delete_playlist(self, rating_key: str) -> None:
        """Delete a playlist by ratingKey.

        Spec: ``DELETE /playlists/{playlistKey}``.
        """
        self._send("DELETE", f"/playlists/{rating_key}")

    # -- search / discovery (spec: Hub) --------------------------------------

    def search_library(
        self, section_id: str, query: str
    ) -> list[HubResult]:
        """Search within a library section.

        Spec: ``GET /library/sections/{sectionKey}/search`` or
        ``GET /hubs/sections/{sectionKey}/search``.
        """
        data = self._get(
            f"/hubs/sections/{section_id}/search", query=query
        )
        hubs = data.get("MediaContainer", {}).get("Hub") or []
        return [_parse_hub(h) for h in hubs]

    def search_all(self, query: str, limit: int = 5) -> list[HubResult]:
        """Global search across all hubs.

        Spec: ``GET /hubs/search``.
        """
        data = self._get("/hubs/search", query=query, limit=limit)
        hubs = data.get("MediaContainer", {}).get("Hub") or []
        return [_parse_hub(h) for h in hubs]

    # -- butler / maintenance ------------------------------------------------

    def run_butler_task(self, task_name: str) -> None:
        """Trigger a Plex Butler (scheduled maintenance) task immediately.

        Spec: ``POST /butler/{taskName}`` (undocumented).

        Common task names: ``MusicAnalysis`` (sonic analysis),
        ``LoudnessAnalysis``, ``DeepMediaAnalysis``. See ``GET /butler`` for
        the tasks available on a given server.
        """
        self._send("POST", f"/butler/{task_name}")

    # -- activities (no spec equivalent) -------------------------------------

    def get_activities(self) -> list[ActivityInfo]:
        """Return currently running server activities.

        The endpoint answers in JSON when asked via ``Accept: application/json``
        and in XML otherwise; handle both.
        """
        resp = self._send("GET", "/activities")

        if "json" in (resp.headers.get("content-type") or ""):
            items = resp.json().get("MediaContainer", {}).get("Activity") or []
            return [
                ActivityInfo(
                    type=item.get("type", ""),
                    title=item.get("title", ""),
                    subtitle=item.get("subtitle", ""),
                    progress=(
                        int(item["progress"])
                        if str(item.get("progress", "")).isdigit()
                        else None
                    ),
                )
                for item in items
            ]

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            return []

        activities = []
        for el in root.iter("Activity"):
            progress = el.get("progress")
            activities.append(
                ActivityInfo(
                    type=el.get("type", ""),
                    title=el.get("title", ""),
                    subtitle=el.get("subtitle", ""),
                    progress=(
                        int(progress) if progress and progress.isdigit() else None
                    ),
                )
            )
        return activities


# ---------------------------------------------------------------------------
# Internal parsers (continued)
# ---------------------------------------------------------------------------


def _parse_hub(raw: dict[str, Any]) -> HubResult:
    """Parse a raw hub dict into a HubResult (spec: ``Hub``)."""
    entries_raw = raw.get("Hub") or []
    entries = []
    for e in entries_raw:
        meta = e.get("Metadata") or []
        entries.append(
            HubEntry(
                key=e.get("key", ""),
                title=e.get("title", ""),
                type=e.get("type", ""),
                hub_identifier=e.get("hubIdentifier"),
                context=e.get("context"),
                size=e.get("size"),
                items=[_parse_media_item(m) for m in meta],
                more=e.get("more", False),
            )
        )
    return HubResult(
        size=raw.get("size"),
        identifier=raw.get("identifier"),
        title=raw.get("title1") or raw.get("title2"),
        entries=entries,
        more=raw.get("more", False),
    )
