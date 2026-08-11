"""JSON endpoints for sonic analysis coverage and refresh."""

from __future__ import annotations

from fastapi import APIRouter, Query

from musicseed_api.handlers.sonic import get_sonic_coverage, trigger_sonic_refresh

router = APIRouter(tags=["sonic"])


@router.get("/sonic/status")
def sonic_status(
    library_name: str | None = Query(default=None),
    recent_days: int = Query(default=7),
) -> dict:
    return get_sonic_coverage(library_name, recent_days=recent_days).model_dump()


@router.post("/sonic/refresh")
def sonic_refresh(
    library_name: str | None = Query(default=None),
    days: int = Query(default=7),
) -> dict:
    result = trigger_sonic_refresh(library_name, days=days)
    return result.model_dump()
