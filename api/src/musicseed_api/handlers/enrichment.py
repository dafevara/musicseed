"""Enrichment orchestration — credential management and enrichment job runnable."""

from __future__ import annotations

from musicseed.config import get_config, set_config
from musicseed.services.enrichment import enrich_tracks
from musicseed.services.jobs import update_progress

ENRICH_KIND = "enrich"


def save_spotify_creds(client_id: str, client_secret: str) -> None:
    """Persist Spotify credentials to config. No-op when both are empty."""
    if not client_id and not client_secret:
        return
    cfg = get_config()
    if client_id:
        cfg.spotify.client_id = client_id
    if client_secret:
        cfg.spotify.client_secret = client_secret
    set_config(cfg)


def run_enrich_job(job_id: int) -> None:
    """Job target: enrich tracks via Spotify and update job progress."""
    update_progress(job_id, 0, 1, "enriching via Spotify…")
    stats = enrich_tracks(source="spotify", resume=True, batch_size=10, concurrency=10)
    update_progress(
        job_id,
        stats.enriched,
        stats.total,
        f"Enriched {stats.enriched:,} of {stats.total:,} tracks",
    )
