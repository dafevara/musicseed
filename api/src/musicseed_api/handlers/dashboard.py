"""Dashboard aggregation — combines discovery, library stats, and job state."""

from __future__ import annotations

from musicseed.services.dashboard import DashboardSnapshot, get_dashboard


def get_dashboard_snapshot() -> DashboardSnapshot:
    return get_dashboard()
