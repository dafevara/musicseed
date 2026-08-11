"""First-run setup wizard routes.

Thin surface: all orchestration lives in ``musicseed_api.handlers.discovery``.
Routes only parse HTTP, call handlers, and render templates. Tokens arrive via
POST bodies and are never logged, rendered, or placed in URLs.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from musicseed_api.handlers.discovery import (
    apply_config_and_init_db,
    extract_overrides,
    run_discovery,
    wizard_ready,
)

from musicseed_web.render import templates

router = APIRouter()


def _render_results(
    request: Request,
    *,
    overrides: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
    db_init: str | None = None,
) -> HTMLResponse:
    discovery_kwargs = overrides if overrides is not None else (form or {})
    result = run_discovery(**discovery_kwargs)
    template_form = form if form is not None else (overrides or {})
    return templates.TemplateResponse(
        request,
        "_setup_results.html",
        {
            "result": result,
            "ready": wizard_ready(result),
            "form": template_form,
            "db_init": db_init,
        },
    )


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "setup.html")


@router.get("/setup/results", response_class=HTMLResponse)
def setup_results(request: Request) -> HTMLResponse:
    """Automatic discovery, run on page load via HTMX — no typing needed."""
    return _render_results(request, form={})


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
    overrides, form = extract_overrides(
        musicseed_db_path=musicseed_db_path,
        plex_db_path=plex_db_path,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
    )
    return _render_results(request, overrides=overrides, form=form)


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
    overrides, form = extract_overrides(
        musicseed_db_path=musicseed_db_path,
        plex_db_path=plex_db_path,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
    )

    db_init: str | None = None
    try:
        apply_config_and_init_db(**overrides)
    except Exception as e:
        db_init = str(e)
    else:
        db_init = "done"
    return _render_results(request, overrides=overrides, form=form, db_init=db_init)
