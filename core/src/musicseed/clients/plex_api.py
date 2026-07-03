"""Plex Media Server HTTP API client."""

from __future__ import annotations

import httpx
from pydantic import BaseModel


class PlexAPIError(RuntimeError):
    """Raised for Plex API errors that should be surfaced to the user."""


class PlaylistResult(BaseModel):
    model_config = {"frozen": True}

    rating_key: str
    title: str


class PlexClient:
    """Thin synchronous client for Plex Media Server playlist operations."""

    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {
            "X-Plex-Token": token,
            "Accept": "application/json",
        }
        self._timeout = timeout

    def _get(self, path: str, **params: str) -> dict:
        try:
            resp = httpx.get(
                f"{self._base}{path}",
                headers=self._headers,
                params=params or None,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError as e:
            raise PlexAPIError(
                f"Cannot reach Plex at {self._base}. Is Plex Media Server running?"
            ) from e
        except httpx.HTTPStatusError as e:
            raise PlexAPIError(
                f"Plex returned HTTP {e.response.status_code} for GET {path}. "
                "Check your plex.token in config."
            ) from e

    def _post(self, path: str, **params: str) -> dict:
        try:
            resp = httpx.post(
                f"{self._base}{path}",
                headers=self._headers,
                params=params or None,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError as e:
            raise PlexAPIError(
                f"Cannot reach Plex at {self._base}. Is Plex Media Server running?"
            ) from e
        except httpx.HTTPStatusError as e:
            raise PlexAPIError(
                f"Plex returned HTTP {e.response.status_code} for POST {path}. "
                "Check your plex.token in config."
            ) from e

    def _put(self, path: str, **params: str) -> dict:
        try:
            resp = httpx.put(
                f"{self._base}{path}",
                headers=self._headers,
                params=params or None,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except httpx.ConnectError as e:
            raise PlexAPIError(
                f"Cannot reach Plex at {self._base}. Is Plex Media Server running?"
            ) from e
        except httpx.HTTPStatusError as e:
            raise PlexAPIError(
                f"Plex returned HTTP {e.response.status_code} for PUT {path}. "
                "Check your plex.token in config."
            ) from e

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
