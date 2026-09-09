"""Sonic analysis orchestration — coverage, refresh, and vector import."""

from __future__ import annotations

import json

from musicseed.services.jobs import complete_job, get_manager, update_progress
from musicseed.services.plex_analysis import (
    SonicRefreshResult,
    SonicStatusResult,
    get_sonic_status,
    refresh_sonic_analysis,
)
from musicseed.services.sonic_vectors import import_plex_sonic
from musicseed.sonic import reset_sonic_vectors

SONIC_IMPORT_KIND = "sonic_import"


def get_sonic_coverage(
    library_name: str | None = None,
    recent_days: int = 7,
) -> SonicStatusResult:
    """Report Plex sonic analysis coverage for a music library.

    Args:
        library_name: Plex music library to inspect; defaults to the
            configured library.
        recent_days: size of the "recent additions" window in days.

    Returns:
        The core ``SonicStatusResult`` as-is.
    """
    return get_sonic_status(library_name, recent_days=recent_days)


def trigger_sonic_refresh(
    library_name: str | None = None,
    days: int = 7,
    wait_seconds: float = 900.0,
) -> SonicRefreshResult:
    """Trigger a Plex sonic analysis refresh and reset the cached vectors.

    Args:
        library_name: Plex music library to refresh; defaults to the
            configured library.
        days: size of the "recent additions" window in days.
        wait_seconds: maximum time to watch the refresh.

    Returns:
        The core ``SonicRefreshResult`` as-is.
    """
    result = refresh_sonic_analysis(
        library_name,
        days=days,
        wait_seconds=wait_seconds,
    )
    # The Butler task may have analyzed new tracks; drop the cached matrix so
    # the next scoring run reflects them.
    reset_sonic_vectors()
    return result


def run_sonic_import_job(job_id: int) -> None:
    """Job target: import Plex sonic vectors into the local store."""
    update_progress(job_id, 0, 1, "importing Plex sonic vectors…")

    cancelled = [False]

    def should_cancel() -> bool:
        if get_manager().should_cancel(job_id):
            cancelled[0] = True
            return True
        return False

    def on_progress(current: int, total: int, message: str) -> None:
        update_progress(job_id, current, total, message)

    stats = import_plex_sonic(
        progress_callback=on_progress,
        should_cancel=should_cancel,
    )

    processed = stats.imported + stats.updated
    if cancelled[0]:
        update_progress(job_id, processed, stats.total, "cancelled")
        return

    checkpoint = f"Imported {processed:,} of {stats.total:,} Plex sonic vectors"
    update_progress(job_id, processed, stats.total, checkpoint)
    complete_job(
        job_id,
        result_summary=json.dumps({
            "total": stats.total,
            "imported": stats.imported,
            "updated": stats.updated,
        }),
    )
