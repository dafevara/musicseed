"""Shared template engine and package paths."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from musicseed_web.nav import nav_context

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(
    directory=BASE_DIR / "templates",
    context_processors=[nav_context],
)
