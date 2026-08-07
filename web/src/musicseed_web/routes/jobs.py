"""Job progress and control routes — consumed by the setup wizard and dashboard."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from musicseed.config import get_config, set_config
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


@router.get("/jobs/{job_id}/progress", response_class=HTMLResponse)
def job_progress(job_id: int, request: Request) -> HTMLResponse:
    j = get_job(job_id)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": j})


@router.post("/setup/start-work", response_class=HTMLResponse)
def start_work(request: Request) -> HTMLResponse:
    """Create an import job. Spotify creds are saved to config for the
    enrichment step that follows."""
    mgr = get_manager()
    try:
        jid = mgr.submit(_IMPORT_KIND, _run_import)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "_job_error.html", {"error": str(e)}, status_code=409
        )
    j = get_job(jid)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": j})


@router.post("/setup/start-enrich", response_class=HTMLResponse)
def start_enrich(
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


@router.post("/jobs/{job_id}/cancel", response_class=HTMLResponse)
def cancel_job_route(job_id: int, request: Request) -> HTMLResponse:
    mgr = get_manager()
    mgr.request_cancel(job_id)
    j = get_job(jid=job_id)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": j})
