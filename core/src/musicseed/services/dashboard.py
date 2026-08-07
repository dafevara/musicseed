"""Dashboard aggregation service — combines discovery, library stats, and
job status into one surface-agnostic snapshot.
"""

from pydantic import BaseModel

from musicseed.services.discovery import DiscoveryResult, discover
from musicseed.services.jobs import JobState, get_active_jobs, get_latest_job, list_jobs
from musicseed.services.library import EnrichmentCoverage, LibraryStatus, get_status


class DashboardSnapshot(BaseModel):
    model_config = {"frozen": True}

    discovery: DiscoveryResult
    library: LibraryStatus
    active_jobs: list[dict]
    recent_jobs: list[dict]
    last_sync: dict | None

    @property
    def ready_for_recommendations(self) -> bool:
        return self.library.track_count > 0


def get_dashboard() -> DashboardSnapshot:
    discovery_result = discover(check_server=True)
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
