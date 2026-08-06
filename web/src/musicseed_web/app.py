"""Application assembly for the MusicSeed local web UI.

Thin surface only: routes render templates and (in later issues) call
``musicseed.services`` for real work. No business, Plex, database, or
recommendation logic lives here.
"""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def create_app() -> FastAPI:
    app = FastAPI(title="MusicSeed", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "musicseed-web"}

    @app.get("/fragments/clock", response_class=HTMLResponse)
    def clock_fragment(request: Request) -> HTMLResponse:
        now = datetime.now(UTC).strftime("%H:%M:%S UTC")
        return templates.TemplateResponse(request, "_clock.html", {"now": now})

    return app


app = create_app()
