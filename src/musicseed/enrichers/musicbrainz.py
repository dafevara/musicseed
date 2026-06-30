"""MusicBrainz API client for MBID to Spotify ID lookups."""

import asyncio
import re

import httpx
from pydantic import BaseModel

from musicseed.logging_config import get_logger

logger = get_logger("enrichers.musicbrainz")

# MusicBrainz API
MB_API_BASE = "https://musicbrainz.org/ws/2"
MB_USER_AGENT = "MusicSeed/0.1.0 (https://github.com/user/musicseed)"

# Rate limit: 1 request per second
MB_RATE_LIMIT = 1.0


class MBRecordingInfo(BaseModel):
    """Info from MusicBrainz recording lookup."""

    mbid: str
    spotify_id: str | None
    title: str | None
    artist: str | None


def extract_spotify_id_from_url(url: str) -> str | None:
    """Extract Spotify track ID from a Spotify URL.

    Examples:
        https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh
        spotify:track:4iV5W9uYEdYUVa79Axb7Rh
    """
    # URL format
    match = re.search(r"open\.spotify\.com/track/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)

    # URI format
    match = re.search(r"spotify:track:([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)

    return None


class MusicBrainzClient:
    """Async MusicBrainz API client with rate limiting."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0

    async def __aenter__(self) -> "MusicBrainzClient":
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": MB_USER_AGENT},
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _rate_limit(self) -> None:
        """Enforce rate limit of 1 request per second."""
        import time

        now = time.time()
        elapsed = now - self._last_request_time

        if elapsed < MB_RATE_LIMIT:
            wait_time = MB_RATE_LIMIT - elapsed
            await asyncio.sleep(wait_time)

        self._last_request_time = time.time()

    async def lookup_recording(self, mbid: str) -> MBRecordingInfo:
        """Look up a recording by MBID and extract Spotify ID if available.

        Args:
            mbid: MusicBrainz recording ID

        Returns:
            MBRecordingInfo with spotify_id if found
        """
        await self._rate_limit()

        url = f"{MB_API_BASE}/recording/{mbid}"
        params = {
            "inc": "url-rels artist-credits",
            "fmt": "json",
        }

        try:
            response = await self._client.get(url, params=params)

            if response.status_code == 404:
                logger.debug(f"MBID not found: {mbid}")
                return MBRecordingInfo(mbid=mbid, spotify_id=None, title=None, artist=None)

            if response.status_code == 503:
                # Service unavailable, wait and retry
                logger.warning("MusicBrainz rate limited, waiting...")
                await asyncio.sleep(5)
                return await self.lookup_recording(mbid)

            response.raise_for_status()
            data = response.json()

            # Extract title and artist
            title = data.get("title")
            artist = None
            if data.get("artist-credit"):
                artist = data["artist-credit"][0].get("name")

            # Look for Spotify URL in relations
            spotify_id = None
            for relation in data.get("relations", []):
                if relation.get("type") == "streaming":
                    url_info = relation.get("url", {})
                    resource = url_info.get("resource", "")
                    if "spotify.com" in resource:
                        spotify_id = extract_spotify_id_from_url(resource)
                        if spotify_id:
                            logger.debug(f"Found Spotify ID {spotify_id} for MBID {mbid}")
                            break

            return MBRecordingInfo(
                mbid=mbid,
                spotify_id=spotify_id,
                title=title,
                artist=artist,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error looking up MBID {mbid}: {e}")
            return MBRecordingInfo(mbid=mbid, spotify_id=None, title=None, artist=None)
        except Exception as e:
            logger.error(f"Error looking up MBID {mbid}: {e}")
            return MBRecordingInfo(mbid=mbid, spotify_id=None, title=None, artist=None)
