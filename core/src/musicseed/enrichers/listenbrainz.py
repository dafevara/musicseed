"""ListenBrainz API client for popularity enrichment."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel

from musicseed.logging_config import get_logger

logger = get_logger("enrichers.listenbrainz")

LISTENBRAINZ_API_BASE = "https://api.listenbrainz.org"
LISTENBRAINZ_USER_AGENT = "MusicSeed/0.1.0 (https://github.com/user/musicseed)"


class ListenBrainzRecordingPopularity(BaseModel):
    """Popularity data for one MusicBrainz recording."""

    model_config = {"frozen": True}

    recording_mbid: str
    total_listen_count: int | None
    total_user_count: int | None


class ListenBrainzClient:
    """Async ListenBrainz client for batched recording popularity lookups."""

    def __init__(self, requests_per_second: float = 1.0):
        self.requests_per_second = requests_per_second
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0

    async def __aenter__(self) -> "ListenBrainzClient":
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": LISTENBRAINZ_USER_AGENT},
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _throttle(self) -> None:
        import time

        now = time.time()
        min_interval = 1.0 / self.requests_per_second
        elapsed = now - self._last_request_time
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> Any:
        if self._client is None:
            raise RuntimeError("ListenBrainzClient must be used as an async context manager")

        await self._throttle()
        url = f"{LISTENBRAINZ_API_BASE}{endpoint}"

        for attempt in range(3):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(f"ListenBrainz rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.RequestError as e:
                logger.warning(f"ListenBrainz request failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise
            except httpx.HTTPStatusError:
                if attempt < 2 and response.status_code >= 500:
                    await asyncio.sleep(2**attempt)
                    continue
                raise

        raise RuntimeError("ListenBrainz request failed after retries")

    async def get_recording_popularity(
        self, recording_mbids: list[str]
    ) -> list[ListenBrainzRecordingPopularity]:
        """Fetch listen/user counts for MusicBrainz recording IDs."""
        if not recording_mbids:
            return []

        data = await self._post(
            "/1/popularity/recording",
            {"recording_mbids": recording_mbids},
        )
        results = []
        for item in data:
            results.append(
                ListenBrainzRecordingPopularity(
                    recording_mbid=item["recording_mbid"],
                    total_listen_count=item.get("total_listen_count"),
                    total_user_count=item.get("total_user_count"),
                )
            )
        return results
