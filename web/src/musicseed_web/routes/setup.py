"""First-run setup wizard routes.

Thin surface: all probing goes through ``musicseed.services.discovery``.
Routes never touch the filesystem or Plex directly and never start
import/enrichment. Tokens arrive via POST bodies and are never logged,
rendered, or placed in URLs.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from musicseed.config import get_config, set_config
from musicseed.db.session import reset_engine
from musicseed.services.discovery import DiscoveryResult, Reason, discover
from musicseed.services.library import initialize_database

from musicseed_web.render import templates

router = APIRouter()

# A missing MusicSeed database is the normal fresh-install state — database
# initialization (a later setup step) creates the parent directory. Only real
# access problems block the wizard.
_DB_BLOCKERS = {Reason.NOT_A_FILE, Reason.NOT_WRITABLE, Reason.PARENT_NOT_WRITABLE}


def _wizard_ready(result: DiscoveryResult) -> bool:
    return (
        result.musicseed_db.reason not in _DB_BLOCKERS
        and result.plex_library_db.ok
        and result.plex_blobs_db.ok
        and result.plex_server.ok
    )


def _render_results(
    request: Request,
    result: DiscoveryResult,
    form: dict[str, str],
    *,
    db_init: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "_setup_results.html",
        {
            "result": result,
            "ready": _wizard_ready(result),
            "form": form,
            "db_init": db_init,
        },
    )


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "setup.html")


@router.get("/setup/results", response_class=HTMLResponse)
def setup_results(request: Request) -> HTMLResponse:
    """Automatic discovery, run on page load via HTMX — no typing needed."""
    return _render_results(request, discover(), form={})


@router.post("/setup/check", response_class=HTMLResponse)
def setup_check(
    request: Request,
    musicseed_db_path: Annotated[str, Form()] = "",
    plex_db_path: Annotated[str, Form()] = "",
    plex_url: Annotated[str, Form()] = "",
    plex_token: Annotated[str, Form()] = "",
    plex_library: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Re-run discovery with manual overrides. Blanks keep automatic values."""
    overrides = {
        key: value.strip()
        for key, value in {
            "musicseed_db_path": musicseed_db_path,
            "plex_db_path": plex_db_path,
            "plex_url": plex_url,
            "plex_token": plex_token,
            "plex_library": plex_library,
        }.items()
        if value.strip()
    }
    result = discover(**overrides)
    # Keep non-secret values sticky for the next retry; never echo the token.
    form = {k: v for k, v in overrides.items() if k != "plex_token"}
    return _render_results(request, result, form)


@router.post("/setup/init-db", response_class=HTMLResponse)
def setup_init_db(
    request: Request,
    musicseed_db_path: Annotated[str, Form()] = "",
    plex_db_path: Annotated[str, Form()] = "",
    plex_url: Annotated[str, Form()] = "",
    plex_token: Annotated[str, Form()] = "",
    plex_library: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Create or validate the MusicSeed SQLite database."""
    overrides = {
        key: value.strip()
        for key, value in {
            "musicseed_db_path": musicseed_db_path,
            "plex_db_path": plex_db_path,
            "plex_url": plex_url,
            "plex_token": plex_token,
            "plex_library": plex_library,
        }.items()
        if value.strip()
    }

    db_path = overrides.get("musicseed_db_path", "")
    try:
        if db_path:
            cfg = get_config()
            cfg.database.path = db_path
            set_config(cfg)
            reset_engine()
        initialize_database()
    except Exception as e:
        result = discover(**overrides) if overrides else discover()
        form = {k: v for k, v in overrides.items() if k != "plex_token"}
        return _render_results(request, result, form, db_init=str(e))

    # Re-run discovery to pick up the now-existing database.
    result = discover(**overrides) if overrides else discover()
    form = {k: v for k, v in overrides.items() if k != "plex_token"}
    return _render_results(request, result, form, db_init="done")
