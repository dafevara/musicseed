"""Dashboard routes — the post-setup home page with library health,
coverage, job status, and actions.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from musicseed.config import get_config, set_config
from musicseed.services.dashboard import get_dashboard
from musicseed.services.enrichment import enrich_tracks
from musicseed.services.jobs import get_job, get_manager, update_progress
from musicseed.services.library import import_library

from musicseed_web.render import templates

router = APIRouter()
_IMPORT_KIND = "import"
_ENRICH_KIND = "enrich"


def _set_spotify_creds(client_id: str, client_secret: str) -> None:
    if client_id or client_secret:
        cfg = get_config()
        if client_id:
            cfg.spotify.client_id = client_id
        if client_secret:
            cfg.spotify.client_secret = client_secret
        set_config(cfg)


def _run_import(job_id: int) -> None:
    update_progress(job_id, 0, 1, "importing library…")
    result = import_library()
    update_progress(
        job_id,
        result.tracks,
        result.tracks,
        f"Imported {result.tracks:,} tracks, {result.artists:,} artists, "
        f"{result.albums:,} albums",
    )


def _run_enrich(job_id: int) -> None:
    update_progress(job_id, 0, 1, "enriching via Spotify…")
    stats = enrich_tracks(source="spotify", resume=True, batch_size=10, concurrency=10)
    update_progress(
        job_id,
        stats.enriched,
        stats.total,
        f"Enriched {stats.enriched:,} of {stats.total:,} tracks",
    )


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    snapshot = get_dashboard()
    return templates.TemplateResponse(request, "dashboard.html", {"snapshot": snapshot})


@router.get("/dashboard/status", response_class=HTMLResponse)
def dashboard_status(request: Request) -> HTMLResponse:
    snapshot = get_dashboard()
    return templates.TemplateResponse(
        request, "_dashboard_status.html", {"snapshot": snapshot}
    )


@router.post("/dashboard/enrich", response_class=HTMLResponse)
def dashboard_enrich(
    request: Request,
    spotify_client_id: Annotated[str, Form()] = "",
    spotify_client_secret: Annotated[str, Form()] = "",
) -> HTMLResponse:
    _set_spotify_creds(spotify_client_id.strip(), spotify_client_secret.strip())
    mgr = get_manager()
    try:
        jid = mgr.submit(_ENRICH_KIND, _run_enrich)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "_job_error.html", {"error": str(e)}, status_code=409
        )
    j = get_job(jid)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": j})


@router.post("/dashboard/sync", response_class=HTMLResponse)
def dashboard_sync(request: Request) -> HTMLResponse:
    mgr = get_manager()
    try:
        jid = mgr.submit(_IMPORT_KIND, _run_import)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "_job_error.html", {"error": str(e)}, status_code=409
        )
    j = get_job(jid)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": j})
