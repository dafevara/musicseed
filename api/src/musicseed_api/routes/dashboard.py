"""JSON endpoint for the aggregated dashboard snapshot."""

from __future__ import annotations

from fastapi import APIRouter, Query

from musicseed_api.handlers.dashboard import get_dashboard_snapshot

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(check_server: bool = Query(default=False)) -> dict:
    return get_dashboard_snapshot(check_server=check_server).model_dump()
