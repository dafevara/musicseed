"""Dashboard aggregation — combines discovery, library stats, and job state."""

from __future__ import annotations

from musicseed.services.dashboard import DashboardSnapshot, get_dashboard


def get_dashboard_snapshot(check_server: bool = False) -> DashboardSnapshot:
    return get_dashboard(check_server=check_server)
