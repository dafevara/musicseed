"""Library orchestration — status and import job runnable."""

from __future__ import annotations

import json

from musicseed.services.jobs import complete_job, update_progress
from musicseed.services.library import LibraryStatus, get_status, import_library

IMPORT_KIND = "import"


def get_library_status() -> LibraryStatus:
    return get_status()


def run_import_job(job_id: int) -> None:
    """Job target: import the Plex library and update job progress."""
    update_progress(job_id, 0, 1, "importing library…")

    last_phase = [0, 0]

    def on_progress(current: int, total: int, phase: str) -> None:
        last_phase[0] = current
        last_phase[1] = total
        update_progress(job_id, current, total, f"importing {phase}…")

    result = import_library(progress_callback=on_progress)

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
