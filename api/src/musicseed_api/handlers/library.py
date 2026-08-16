"""Library orchestration — status and import job runnable."""

from __future__ import annotations

import json

from musicseed.services.jobs import complete_job, get_manager, update_progress
from musicseed.services.library import LibraryStatus, get_status, import_library

IMPORT_KIND = "import"


def get_library_status() -> LibraryStatus:
    """Return local library statistics and enrichment coverage.

    Returns:
        The core ``LibraryStatus`` result model as-is.
    """
    return get_status()


def run_import_job(job_id: int) -> None:
    """Job target: import the Plex library and update job progress."""
    update_progress(job_id, 0, 1, "importing library…")

    cancelled = [False]
    phases: dict[str, dict[str, int]] = {}

    def should_cancel() -> bool:
        if get_manager().should_cancel(job_id):
            cancelled[0] = True
            return True
        return False

    def on_progress(current: int, total: int, phase: str) -> None:
        phases[phase] = {"current": current, "total": total}
        update_progress(
            job_id, current, total, f"importing {phase}…", phases=phases,
        )

    result = import_library(progress_callback=on_progress, should_cancel=should_cancel)

    if cancelled[0]:
        update_progress(job_id, result.tracks, result.tracks, "cancelled")
        return

    checkpoint = (
        f"Imported {result.tracks:,} tracks, {result.artists:,} artists, "
        f"{result.albums:,} albums"
    )
    update_progress(
        job_id,
        result.tracks,
        result.tracks,
        checkpoint,
    )

    complete_job(
        job_id,
        result_summary=json.dumps({
            "tracks": result.tracks,
            "artists": result.artists,
            "albums": result.albums,
            "play_history": result.play_history,
        }),
    )
