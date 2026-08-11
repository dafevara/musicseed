"""Home page, health check, and small demo fragment routes.

Thin surface: routes delegate to ``musicseed_api.handlers`` for all
orchestration and call core services only for simple read-only probes
where no orchestration is needed.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from musicseed.services.discovery import discover
from musicseed_api.handlers.dashboard import get_dashboard_snapshot

from musicseed_web.render import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if not discover(check_server=False).musicseed_db.exists:
        return RedirectResponse("/setup", status_code=303)
    snapshot = get_dashboard_snapshot()
    return templates.TemplateResponse(request, "dashboard.html", {"snapshot": snapshot})


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "musicseed-web"}


@router.get("/fragments/clock", response_class=HTMLResponse)
def clock_fragment(request: Request) -> HTMLResponse:
    now = datetime.now(UTC).strftime("%H:%M:%S UTC")
    return templates.TemplateResponse(request, "_clock.html", {"now": now})
