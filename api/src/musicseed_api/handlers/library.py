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
    """Job target for the import story line (runs in a ``JobManager`` thread).

    ``routes.library.start_import`` submits this callable; the manager runs it
    in a daemon thread with a persisted job row. This function drives core's
    ``import_library``, translating its ``(current, total, phase)`` progress
    into ``update_progress`` checkpoints for the UI, then records a
    ``complete_job`` result summary on success (the manager finalizes the row
    once the target returns).

    Cancellation is cooperative: ``should_cancel`` asks the job manager on
    every importer poll, and a cancelled run emits a ``cancelled`` checkpoint
    and returns without recording success.

    Args:
        job_id: the job row id assigned by the job manager (always the first
            positional argument, per the manager convention).
    """
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
        checkpoint = phase if phase == "downloading Plex database" else f"importing {phase}"
        update_progress(
            job_id, current, total, f"{checkpoint}…", phases=phases,
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
