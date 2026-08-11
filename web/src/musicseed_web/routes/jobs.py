"""Job progress and control routes — consumed by the setup wizard and dashboard.

Thin surface: routes delegate to ``musicseed_api.handlers`` for all
orchestration. No config manipulation or job runnables appear here.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from musicseed_api.handlers.enrichment import ENRICH_KIND, run_enrich_job, save_spotify_creds
from musicseed_api.handlers.jobs import cancel_job, get_job_progress, submit_job
from musicseed_api.handlers.library import IMPORT_KIND, run_import_job

from musicseed_web.render import templates

router = APIRouter()


@router.get("/jobs/{job_id}/progress", response_class=HTMLResponse)
def job_progress(job_id: int, request: Request) -> HTMLResponse:
    job = get_job_progress(job_id)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": job})


@router.post("/setup/start-work", response_class=HTMLResponse)
def start_work(request: Request) -> HTMLResponse:
    """Create an import job."""
    try:
        jid = submit_job(IMPORT_KIND, run_import_job)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "_job_error.html", {"error": str(e)}, status_code=409
        )
    job = get_job_progress(jid)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": job})


@router.post("/setup/start-enrich", response_class=HTMLResponse)
def start_enrich(
    request: Request,
    spotify_client_id: Annotated[str, Form()] = "",
    spotify_client_secret: Annotated[str, Form()] = "",
) -> HTMLResponse:
    save_spotify_creds(spotify_client_id.strip(), spotify_client_secret.strip())
    try:
        jid = submit_job(ENRICH_KIND, run_enrich_job)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "_job_error.html", {"error": str(e)}, status_code=409
        )
    job = get_job_progress(jid)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": job})


@router.post("/jobs/{job_id}/cancel", response_class=HTMLResponse)
def cancel_job_route(job_id: int, request: Request) -> HTMLResponse:
    cancel_job(job_id)
    job = get_job_progress(job_id)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": job})
