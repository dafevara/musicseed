"""Plex Media Server HTTP API client."""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel


class PlexAPIError(RuntimeError):
    """Raised for Plex API errors that should be surfaced to the user."""


class PlaylistResult(BaseModel):
    model_config = {"frozen": True}

    rating_key: str
    title: str


class LibrarySectionResult(BaseModel):
    model_config = {"frozen": True}

    key: str
    title: str
    type: str


class SectionTrack(BaseModel):
    """A music track as reported by the Plex HTTP API."""

    model_config = {"frozen": True}

    rating_key: str
    title: str
    album_rating_key: str | None
    album_title: str | None
    artist_title: str | None
    added_at: datetime | None
    has_sonic_analysis: bool


class ActivityInfo(BaseModel):
    model_config = {"frozen": True}

    type: str
    title: str
    subtitle: str
    progress: int | None


class PlexClient:
    """Thin synchronous client for Plex Media Server playlist operations."""

    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {
            "X-Plex-Token": token,
            "Accept": "application/json",
        }
        self._timeout = timeout

    def _send(self, method: str, path: str, **params: str) -> httpx.Response:
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

    def _get(self, path: str, **params: str) -> dict:
        return self._send("GET", path, **params).json()

    def _post(self, path: str, **params: str) -> dict:
        return self._send("POST", path, **params).json()

    def _put(self, path: str, **params: str) -> dict:
        resp = self._send("PUT", path, **params)
        return resp.json() if resp.content else {}

    def machine_identifier(self) -> str:
        """Return the Plex server machine identifier (needed to build track URIs)."""
        data = self._get("/")
        return data["MediaContainer"]["machineIdentifier"]

    def find_playlist(self, name: str) -> str | None:
        """Return the ratingKey of an audio playlist with this exact name, or None."""
        data = self._get("/playlists/all", playlistType="audio")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        for item in items:
            if item.get("title") == name:
                return str(item["ratingKey"])
        return None

    def list_playlists(self) -> list[PlaylistResult]:
        """Return every audio playlist on the server."""
        data = self._get("/playlists/all", playlistType="audio")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [
            PlaylistResult(rating_key=str(item["ratingKey"]), title=item["title"])
            for item in items
        ]

    def get_playlist_tracks(self, rating_key: str) -> list[int]:
        """Return the Plex ratingKeys of every track currently in a playlist."""
        data = self._get(f"/playlists/{rating_key}/items")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [int(item["ratingKey"]) for item in items]

    def _metadata_uri(self, plex_ids: list[int]) -> str:
        machine_id = self.machine_identifier()
        ids_str = ",".join(str(pid) for pid in plex_ids)
        return (
            f"server://{machine_id}/com.plexapp.plugins.library"
            f"/library/metadata/{ids_str}"
        )

    def create_playlist(self, name: str, plex_ids: list[int]) -> PlaylistResult:
        """Create an audio playlist in Plex from a list of Plex track ratingKeys.

        Raises PlexAPIError if the name already exists or the id list is empty.
        """
        if not plex_ids:
            raise PlexAPIError(
                f"Cannot create playlist '{name}': none of the recommended tracks "
                "have a Plex ID in the database."
            )

        existing = self.find_playlist(name)
        if existing is not None:
            raise PlexAPIError(
                f"A playlist named '{name}' already exists in Plex (id={existing}). "
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
        return PlaylistResult(rating_key=str(item["ratingKey"]), title=item["title"])

    def add_to_playlist(self, rating_key: str, plex_ids: list[int]) -> None:
        """Add tracks to an existing playlist by Plex track ratingKeys.

        Raises PlexAPIError if the id list is empty.
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

    def list_library_sections(self) -> list[LibrarySectionResult]:
        """Return every library section on the server."""
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

    @staticmethod
    def _parse_track(item: dict) -> SectionTrack:
        added_at = item.get("addedAt")
        return SectionTrack(
            rating_key=str(item["ratingKey"]),
            title=item.get("title", ""),
            album_rating_key=(
                str(item["parentRatingKey"]) if item.get("parentRatingKey") else None
            ),
            album_title=item.get("parentTitle"),
            artist_title=item.get("grandparentTitle"),
            added_at=datetime.fromtimestamp(added_at) if added_at else None,
            has_sonic_analysis="musicAnalysisVersion" in item,
        )

    def get_section_tracks(self, section_id: str) -> list[SectionTrack]:
        """Return every track in a library section (can be slow on big libraries)."""
        data = self._get(f"/library/sections/{section_id}/all", type="10")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [self._parse_track(item) for item in items]

    def get_album_tracks(self, album_rating_key: str) -> list[SectionTrack]:
        """Return the tracks of a single album by its ratingKey."""
        data = self._get(f"/library/metadata/{album_rating_key}/children")
        items = data.get("MediaContainer", {}).get("Metadata") or []
        return [self._parse_track(item) for item in items]

    def analyze_item(self, rating_key: str) -> None:
        """Queue Plex analysis for a single item (artist, album, or track)."""
        self._put(f"/library/metadata/{rating_key}/analyze")

    def refresh_item(self, rating_key: str) -> None:
        """Refresh metadata for a single item (re-reads its files from disk)."""
        self._put(f"/library/metadata/{rating_key}/refresh")

    def run_butler_task(self, task_name: str) -> None:
        """Trigger a Plex Butler (scheduled maintenance) task immediately.

        Common task names: ``MusicAnalysis`` (sonic analysis),
        ``LoudnessAnalysis``, ``DeepMediaAnalysis``. See ``GET /butler`` for
        the tasks available on a given server.
        """
        self._send("POST", f"/butler/{task_name}")

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
                    progress=int(progress) if progress and progress.isdigit() else None,
                )
            )
        return activities
