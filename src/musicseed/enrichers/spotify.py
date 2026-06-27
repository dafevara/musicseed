"""Spotify API client for track enrichment."""

import asyncio
import base64
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import httpx

from musicseed.logging_config import get_logger

logger = get_logger("enrichers.spotify")

# Spotify API endpoints
SPOTIFY_AUTH_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


@dataclass
class SpotifyTrack:
    """Spotify track data."""
    spotify_id: str
    name: str
    artist: str
    album: str
    popularity: int
    duration_ms: int


@dataclass
class MatchResult:
    """Result of matching a local track to Spotify."""
    spotify_track: SpotifyTrack | None
    score: float
    matched: bool


def normalize_string(s: str) -> str:
    """Normalize a string for comparison.

    - Lowercase
    - Remove accents/diacritics
    - Remove special characters
    - Collapse whitespace
    """
    if not s:
        return ""

    # Lowercase
    s = s.lower()

    # Remove accents/diacritics
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))

    # Remove special characters (keep alphanumeric and spaces)
    s = re.sub(r"[^\w\s]", " ", s)

    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()

    return s


def similarity(a: str, b: str) -> float:
    """Calculate similarity ratio between two strings."""
    a_norm = normalize_string(a)
    b_norm = normalize_string(b)
    return SequenceMatcher(None, a_norm, b_norm).ratio()


class SpotifyClient:
    """Async Spotify API client with rate limiting."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        concurrency: int = 5,
        requests_per_second: float = 1.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.concurrency = concurrency
        self.requests_per_second = requests_per_second
        self._access_token: str | None = None
        self._token_expires_at: float = 0
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._rate_limit_reset: float = 0
        self._last_request_time: float = 0

    async def __aenter__(self) -> "SpotifyClient":
        self._client = httpx.AsyncClient(timeout=30.0)
        self._semaphore = asyncio.Semaphore(self.concurrency)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_token(self) -> str:
        """Ensure we have a valid access token."""
        import time

        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        logger.debug("Refreshing Spotify access token")

        # Client credentials flow
        auth_str = f"{self.client_id}:{self.client_secret}"
        auth_b64 = base64.b64encode(auth_str.encode()).decode()

        response = await self._client.post(
            SPOTIFY_AUTH_URL,
            headers={"Authorization": f"Basic {auth_b64}"},
            data={"grant_type": "client_credentials"},
        )
        response.raise_for_status()

        data = response.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data["expires_in"]

        logger.debug("Got new access token")
        return self._access_token

    async def _throttle(self) -> None:
        """Enforce requests per second limit."""
        import time

        now = time.time()
        min_interval = 1.0 / self.requests_per_second
        elapsed = now - self._last_request_time

        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            await asyncio.sleep(wait_time)

        self._last_request_time = time.time()

    async def _request(
        self,
        method: str,
        endpoint: str,
        skip_throttle: bool = False,
        **kwargs,
    ) -> dict[str, Any]:
        """Make an authenticated request with rate limiting."""
        import time

        async with self._semaphore:
            # Apply throttle (unless skip_throttle for batch endpoints)
            if not skip_throttle:
                await self._throttle()

            # Wait if we're rate limited by Spotify
            if time.time() < self._rate_limit_reset:
                wait_time = self._rate_limit_reset - time.time()
                logger.warning(f"Rate limited by Spotify, waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)

            token = await self._ensure_token()
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {token}"

            url = f"{SPOTIFY_API_BASE}{endpoint}"

            for attempt in range(3):
                try:
                    response = await self._client.request(
                        method, url, headers=headers, **kwargs
                    )

                    if response.status_code == 429:
                        # Rate limited
                        retry_after = int(response.headers.get("Retry-After", 5))
                        self._rate_limit_reset = time.time() + retry_after
                        logger.warning(f"Rate limited, retry after {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    response.raise_for_status()
                    return response.json()

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        continue
                    logger.error(f"HTTP error: {e}")
                    raise
                except httpx.RequestError as e:
                    logger.error(f"Request error: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise

            raise RuntimeError("Max retries exceeded")

    async def search_track(
        self,
        title: str,
        artist: str,
        album: str | None = None,
    ) -> list[SpotifyTrack]:
        """Search for a track on Spotify."""
        # Build search query
        query_parts = []

        if title:
            # Clean title - remove common suffixes like (Remaster), [Live], etc.
            clean_title = re.sub(r"\s*[\(\[].*?[\)\]]", "", title).strip()
            query_parts.append(f'track:"{clean_title}"')

        if artist:
            # Use first artist if multiple
            first_artist = artist.split(",")[0].split("&")[0].split("/")[0].strip()
            query_parts.append(f'artist:"{first_artist}"')

        if album:
            clean_album = re.sub(r"\s*[\(\[].*?[\)\]]", "", album).strip()
            query_parts.append(f'album:"{clean_album}"')

        query = " ".join(query_parts)

        logger.debug(f"Searching: {query}")

        try:
            data = await self._request(
                "GET",
                "/search",
                params={"q": query, "type": "track", "limit": 5},
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                # Bad query, try simpler search
                simple_query = f"{title} {artist}"
                logger.debug(f"Retrying with simple query: {simple_query}")
                data = await self._request(
                    "GET",
                    "/search",
                    params={"q": simple_query, "type": "track", "limit": 5},
                )
            else:
                raise

        tracks = []
        for item in data.get("tracks", {}).get("items", []):
            tracks.append(SpotifyTrack(
                spotify_id=item["id"],
                name=item["name"],
                artist=item["artists"][0]["name"] if item["artists"] else "",
                album=item["album"]["name"] if item.get("album") else "",
                popularity=item["popularity"],
                duration_ms=item["duration_ms"],
            ))

        return tracks

    async def get_tracks(self, track_ids: list[str]) -> list[SpotifyTrack]:
        """Get multiple tracks by ID (max 50 per request)."""
        if not track_ids:
            return []

        # Spotify allows max 50 IDs per request
        if len(track_ids) > 50:
            raise ValueError("Max 50 track IDs per request")

        data = await self._request(
            "GET",
            "/tracks",
            skip_throttle=True,  # Batch endpoint, don't throttle
            params={"ids": ",".join(track_ids)},
        )

        tracks = []
        for item in data.get("tracks", []):
            if item:  # Can be null if track not found
                tracks.append(SpotifyTrack(
                    spotify_id=item["id"],
                    name=item["name"],
                    artist=item["artists"][0]["name"] if item["artists"] else "",
                    album=item["album"]["name"] if item.get("album") else "",
                    popularity=item["popularity"],
                    duration_ms=item["duration_ms"],
                ))

        return tracks

    def score_match(
        self,
        local_title: str,
        local_artist: str,
        local_album: str | None,
        local_duration_ms: int | None,
        spotify_track: SpotifyTrack,
    ) -> float:
        """Score how well a Spotify track matches local metadata.

        Returns a score between 0 and 1.
        """
        # Title similarity (weight: 0.4)
        title_sim = similarity(local_title, spotify_track.name)

        # Artist similarity (weight: 0.4)
        artist_sim = similarity(local_artist, spotify_track.artist)

        # Album similarity (weight: 0.1)
        album_sim = 0.5  # Default if no local album
        if local_album:
            album_sim = similarity(local_album, spotify_track.album)

        # Duration similarity (weight: 0.1)
        duration_sim = 0.5  # Default if no local duration
        if local_duration_ms and spotify_track.duration_ms:
            # Allow 5 second tolerance
            diff = abs(local_duration_ms - spotify_track.duration_ms)
            if diff < 5000:
                duration_sim = 1.0
            elif diff < 15000:
                duration_sim = 0.7
            elif diff < 30000:
                duration_sim = 0.3
            else:
                duration_sim = 0.0

        score = (
            title_sim * 0.4 +
            artist_sim * 0.4 +
            album_sim * 0.1 +
            duration_sim * 0.1
        )

        return score

    async def match_track(
        self,
        title: str,
        artist: str,
        album: str | None = None,
        duration_ms: int | None = None,
        threshold: float = 0.7,
    ) -> MatchResult:
        """Find the best matching Spotify track.

        Args:
            title: Track title
            artist: Artist name
            album: Album name (optional)
            duration_ms: Track duration in ms (optional)
            threshold: Minimum score to accept a match

        Returns:
            MatchResult with the best match (if any)
        """
        # Search with album first
        candidates = await self.search_track(title, artist, album)

        # If no results and we had an album, try without it
        if not candidates and album:
            candidates = await self.search_track(title, artist, None)

        if not candidates:
            return MatchResult(spotify_track=None, score=0.0, matched=False)

        # Score all candidates
        best_track = None
        best_score = 0.0

        for track in candidates:
            score = self.score_match(title, artist, album, duration_ms, track)
            if score > best_score:
                best_score = score
                best_track = track

        matched = best_score >= threshold

        if matched:
            logger.debug(
                f"Matched '{title}' by '{artist}' -> "
                f"'{best_track.name}' by '{best_track.artist}' "
                f"(score: {best_score:.2f}, popularity: {best_track.popularity})"
            )
        else:
            logger.debug(
                f"No match for '{title}' by '{artist}' "
                f"(best score: {best_score:.2f})"
            )

        return MatchResult(
            spotify_track=best_track if matched else None,
            score=best_score,
            matched=matched,
        )
