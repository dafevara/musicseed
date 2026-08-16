"""Dashboard aggregation — combines discovery, library stats, and job state."""

from __future__ import annotations

from musicseed.services.dashboard import DashboardSnapshot, get_dashboard


def get_dashboard_snapshot(check_server: bool = False) -> DashboardSnapshot:
    """Return the aggregated dashboard snapshot for surfaces.

    Args:
        check_server: whether to include the live Plex HTTP probe; defaults
            to False so frequent dashboard polls never touch Plex.

    Returns:
        The combined discovery, library, and job snapshot.
    """
    return get_dashboard(check_server=check_server)
