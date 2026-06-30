"""Enrichment service — surface-agnostic entry points for metadata enrichment and embeddings."""

from __future__ import annotations

import asyncio

from musicseed.config import get_config
from musicseed.db.session import ensure_schema, get_session
from musicseed.embeddings.pipeline import EmbeddingStats, run_embedding_pipeline
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
) -> EnrichmentStats:
    """Enrich tracks with external metadata from Spotify or ListenBrainz.

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

    with get_session() as session:
        ensure_schema()
        return asyncio.run(
            run_enrichment(
                session=session,
                source=source,
                client_id=config.spotify.client_id,
                client_secret=config.spotify.client_secret,
                batch_size=batch_size,
                limit=limit,
                artist=artist,
                album=album,
                unattempted_only=resume,
                concurrency=concurrency,
            )
        )


def generate_embeddings(
    model: str = "essentia",
    batch_size: int = 10,
    limit: int | None = None,
    missing_only: bool = True,
    workers: int = 4,
) -> EmbeddingStats:
    """Generate audio embeddings for tracks."""
    with get_session() as session:
        return run_embedding_pipeline(
            session=session,
            model=model,
            batch_size=batch_size,
            limit=limit,
            missing_only=missing_only,
            workers=workers,
        )
