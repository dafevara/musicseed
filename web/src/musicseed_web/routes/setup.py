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

_DB_BLOCKERS = {Reason.NOT_A_FILE, Reason.NOT_WRITABLE, Reason.PARENT_NOT_WRITABLE}
_ALL_FIELDS = (
    "musicseed_db_path", "plex_db_path", "plex_url", "plex_token", "plex_library",
    "spotify_client_id", "spotify_client_secret",
)
_SECRET_FIELDS = {"plex_token", "spotify_client_secret"}


def _wizard_ready(result: DiscoveryResult) -> bool:
    return (
        result.musicseed_db.reason not in _DB_BLOCKERS
        and result.plex_library_db.ok
        and result.plex_blobs_db.ok
        and result.plex_server.ok
    )


def _extract_overrides(
    musicseed_db_path: str, plex_db_path: str, plex_url: str,
    plex_token: str, plex_library: str,
    spotify_client_id: str = "", spotify_client_secret: str = "",
) -> tuple[dict[str, str], dict[str, str]]:
    """Build discovery overrides and a persistent form dict (secrets excluded)."""
    raw = {
        "musicseed_db_path": musicseed_db_path.strip(),
        "plex_db_path": plex_db_path.strip(),
        "plex_url": plex_url.strip(),
        "plex_token": plex_token.strip(),
        "plex_library": plex_library.strip(),
        "spotify_client_id": spotify_client_id.strip(),
        "spotify_client_secret": spotify_client_secret.strip(),
    }
    overrides = {k: v for k, v in raw.items() if v}
    form = {k: v for k, v in overrides.items() if k not in _SECRET_FIELDS}
    return overrides, form


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
    spotify_client_id: Annotated[str, Form()] = "",
    spotify_client_secret: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Re-run discovery with manual overrides. Blanks keep automatic values."""
    overrides, form = _extract_overrides(
        musicseed_db_path, plex_db_path, plex_url, plex_token, plex_library,
        spotify_client_id, spotify_client_secret,
    )
    # Only discovery-relevant keys go to discover()
    disco_keys = {"musicseed_db_path", "plex_db_path", "plex_url", "plex_token", "plex_library"}
    result = discover(**{k: v for k, v in overrides.items() if k in disco_keys})
    return _render_results(request, result, form)


@router.post("/setup/init-db", response_class=HTMLResponse)
def setup_init_db(
    request: Request,
    musicseed_db_path: Annotated[str, Form()] = "",
    plex_db_path: Annotated[str, Form()] = "",
    plex_url: Annotated[str, Form()] = "",
    plex_token: Annotated[str, Form()] = "",
    plex_library: Annotated[str, Form()] = "",
    spotify_client_id: Annotated[str, Form()] = "",
    spotify_client_secret: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Create or validate the MusicSeed SQLite database."""
    overrides, form = _extract_overrides(
        musicseed_db_path, plex_db_path, plex_url, plex_token, plex_library,
        spotify_client_id, spotify_client_secret,
    )
    disco_keys = {"musicseed_db_path", "plex_db_path", "plex_url", "plex_token", "plex_library"}

    db_path = overrides.get("musicseed_db_path", "")
    try:
        cfg = get_config()
        if db_path:
            cfg.database.path = db_path
        if overrides.get("spotify_client_id"):
            cfg.spotify.client_id = overrides["spotify_client_id"]
        if overrides.get("spotify_client_secret"):
            cfg.spotify.client_secret = overrides["spotify_client_secret"]
        if db_path or any(k in overrides for k in ("spotify_client_id", "spotify_client_secret")):
            set_config(cfg)
            reset_engine()
        initialize_database()
    except Exception as e:
        result = discover(**{k: v for k, v in overrides.items() if k in disco_keys})
        return _render_results(request, result, form, db_init=str(e))

    result = discover(**{k: v for k, v in overrides.items() if k in disco_keys})
    return _render_results(request, result, form, db_init="done")
