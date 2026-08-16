"""Dashboard aggregation service — combines discovery, library stats, and
job status into one surface-agnostic snapshot.
"""  # noqa: D205

from pydantic import BaseModel

from musicseed.services.discovery import DiscoveryResult, discover
from musicseed.services.jobs import JobState, get_active_jobs, get_latest_job, list_jobs
from musicseed.services.library import EnrichmentCoverage, LibraryStatus, get_status


class DashboardSnapshot(BaseModel):
    """Combined dashboard view: discovery, library stats, and job state."""

    model_config = {"frozen": True}

    discovery: DiscoveryResult
    library: LibraryStatus
    active_jobs: list[dict]
    recent_jobs: list[dict]
    last_sync: dict | None

    @property
    def ready_for_recommendations(self) -> bool:
        """True when at least one track has been imported locally."""
        return self.library.track_count > 0


def get_dashboard(check_server: bool = False) -> DashboardSnapshot:
    """Aggregate a dashboard snapshot.

    ``check_server`` gates the live Plex HTTP probe inside discovery. It
    defaults to False so frequent dashboard polls never touch Plex; the
    caller (a web surface) fetches the full probe separately and less often.
    When the library status cannot be read (e.g. no database yet), an empty
    ``LibraryStatus`` is used instead of failing the whole snapshot.

    Args:
        check_server: whether to probe the Plex server over HTTP as part of
            the embedded discovery result.

    Returns:
        A snapshot with discovery, library status, active and recent jobs,
        and the last successful import (``last_sync``, None when no import
        has succeeded yet).
    """
    discovery_result = discover(check_server=check_server)
    try:
        library = get_status()
    except Exception:
        library = LibraryStatus(
            db_path="", db_size_bytes=None, plex_url="", plex_db="", plex_library="",
            artist_count=0, album_count=0, track_count=0, play_count=0,
            genre_count=0, mood_count=0, style_count=0,
            enrichment=EnrichmentCoverage(
                tracks_with_mbid=0, tracks_with_spotify=0,
                tracks_with_listenbrainz=0, tracks_with_sonic=0,
                spotify_attempted=0, listenbrainz_attempted=0,
            ),
        )
    active = get_active_jobs()
    recent = list_jobs(limit=10)
    last_sync = get_latest_job("import")
    return DashboardSnapshot(
        discovery=discovery_result,
        library=library,
        active_jobs=active,
        recent_jobs=recent,
        last_sync=(
            last_sync if last_sync and last_sync["state"] == JobState.SUCCEEDED else None
        ),
    )
