"""Enrichment service — surface-agnostic entry points for metadata enrichment."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from musicseed.config import get_config
from musicseed.db.session import ensure_schema
from musicseed.enrichers.pipeline import EnrichmentStats, run_enrichment
from musicseed.exceptions import ConfigurationError


def enrich_tracks(
    source: str = "listenbrainz",
    batch_size: int = 50,
    limit: int | None = None,
    artist: str | None = None,
    album: str | None = None,
    resume: bool = False,
    concurrency: int = 5,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> EnrichmentStats:
    """Enrich tracks with external metadata from Spotify or ListenBrainz.

    Runs the async enrichment pipeline via ``asyncio.run()`` internally —
    never call this from inside a running event loop; offload to a thread
    instead.

    Args:
        source: enrichment source, ``"spotify"`` or ``"listenbrainz"``.
        batch_size: tracks processed per batch.
        limit: maximum number of tracks to enrich (None for all).
        artist: only enrich tracks whose artist name matches this pattern.
        album: only enrich tracks whose album title matches this pattern.
        resume: skip tracks that were already attempted.
        concurrency: maximum concurrent requests inside the async pipeline.
        progress_callback: optional ``(current, total, message)`` callback.
        should_cancel: optional callable polled by the pipeline; enrichment
            stops early when it returns True.

    Returns:
        Aggregate enrichment statistics (processed, matched, unmatched,
        errors).

    Raises:
        ConfigurationError: if Spotify credentials are missing when source='spotify'.
    """
    config = get_config()

    if source == "spotify" and (
        not config.spotify.client_id or not config.spotify.client_secret
    ):
        raise ConfigurationError(
            "Spotify credentials not configured. "
            "Add spotify.client_id and spotify.client_secret to your config file."
        )

    ensure_schema()
    return asyncio.run(
        run_enrichment(
            source=source,
            client_id=config.spotify.client_id,
            client_secret=config.spotify.client_secret,
            batch_size=batch_size,
            limit=limit,
            artist=artist,
            album=album,
            unattempted_only=resume,
            concurrency=concurrency,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
    )
