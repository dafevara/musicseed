"""Home page, health check, and small demo fragment routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from musicseed.services.discovery import discover

from musicseed_web.render import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    # Fresh installations (no MusicSeed database yet) go straight into setup.
    # A configured installation can still reach /setup intentionally via nav.
    if not discover(check_server=False).musicseed_db.exists:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(request, "index.html")


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "musicseed-web"}


@router.get("/fragments/clock", response_class=HTMLResponse)
def clock_fragment(request: Request) -> HTMLResponse:
    now = datetime.now(UTC).strftime("%H:%M:%S UTC")
    return templates.TemplateResponse(request, "_clock.html", {"now": now})
