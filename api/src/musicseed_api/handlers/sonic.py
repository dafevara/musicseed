"""Sonic analysis orchestration — coverage inspection and refresh triggering."""

from __future__ import annotations

from musicseed.services.plex_analysis import (
    SonicRefreshResult,
    SonicStatusResult,
    get_sonic_status,
    refresh_sonic_analysis,
)
from musicseed.sonic import reset_sonic_vectors


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
