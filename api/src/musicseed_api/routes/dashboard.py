"""JSON endpoint for the aggregated dashboard snapshot."""

from __future__ import annotations

from fastapi import APIRouter

from musicseed_api.handlers.dashboard import get_dashboard_snapshot

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard() -> dict:
    return get_dashboard_snapshot().model_dump()
