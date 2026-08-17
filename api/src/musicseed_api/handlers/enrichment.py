"""Enrichment orchestration — credential management and enrichment job runnable."""

from __future__ import annotations

import json

from musicseed.config import get_config, save_config
from musicseed.services.enrichment import enrich_tracks
from musicseed.services.jobs import complete_job, get_manager, update_progress

ENRICH_KIND = "enrich"


def enrich_kind(source: str) -> str:
    """Job kind for an enrichment source.

    Each source gets its own kind (``enrich:spotify`` / ``enrich:listenbrainz``)
    so the job system's one-active-job-per-kind rule applies per source and the
    UI can track each provider's job independently.
    """
    return f"{ENRICH_KIND}:{source}"


def save_spotify_creds(client_id: str, client_secret: str) -> None:
    """Persist Spotify credentials to config. No-op when both are empty."""
    if not client_id and not client_secret:
        return
    cfg = get_config()
    if client_id:
        cfg.spotify.client_id = client_id
    if client_secret:
        cfg.spotify.client_secret = client_secret
    save_config(cfg)


def save_listenbrainz_token(token: str) -> None:
    """Persist the ListenBrainz user token to config. No-op when empty."""
    if not token:
        return
    cfg = get_config()
    cfg.listenbrainz.token = token
    save_config(cfg)


def run_enrich_job(job_id: int, source: str = "spotify") -> None:
    """Job target: enrich tracks via the given source and update job progress."""
    update_progress(job_id, 0, 1, f"enriching via {source}…")

    cancelled = [False]

    def should_cancel() -> bool:
        if get_manager().should_cancel(job_id):
            cancelled[0] = True
            return True
        return False

    def on_progress(current: int, total: int, message: str) -> None:
        update_progress(job_id, current, total, message)

    stats = enrich_tracks(
        source=source,
        resume=True,
        batch_size=10,
        concurrency=10,
        progress_callback=on_progress,
        should_cancel=should_cancel,
    )

    if cancelled[0]:
        update_progress(job_id, stats.matched, stats.total, "cancelled")
        return

    checkpoint = f"Enriched {stats.matched:,} of {stats.total:,} tracks"
    update_progress(
        job_id,
        stats.matched,
        stats.total,
        checkpoint,
    )

    complete_job(
        job_id,
        result_summary=json.dumps({
            "enriched": stats.matched,
            "total": stats.total,
            "errors": stats.errors,
            "source": source,
        }),
    )
