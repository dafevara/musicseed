"""Library orchestration — status and import job runnable."""

from __future__ import annotations

from musicseed.services.jobs import update_progress
from musicseed.services.library import LibraryStatus, get_status, import_library

IMPORT_KIND = "import"


def get_library_status() -> LibraryStatus:
    return get_status()


def run_import_job(job_id: int) -> None:
    """Job target: import the Plex library and update job progress."""
    update_progress(job_id, 0, 1, "importing library…")
    result = import_library()
    update_progress(
        job_id,
        result.tracks,
        result.tracks,
        f"Imported {result.tracks:,} tracks, {result.artists:,} artists, "
        f"{result.albums:,} albums",
    )
