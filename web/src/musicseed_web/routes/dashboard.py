"""Dashboard routes — the post-setup home page with library health,
coverage, job status, and actions.

Thin surface: routes delegate to ``musicseed_api.handlers`` for all
orchestration. No config manipulation, job runnables, or service imports
appear here — that logic lives once in ``api/handlers/``.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from musicseed_api.handlers.dashboard import get_dashboard_snapshot
from musicseed_api.handlers.enrichment import ENRICH_KIND, run_enrich_job, save_spotify_creds
from musicseed_api.handlers.jobs import get_job_progress, submit_job
from musicseed_api.handlers.library import IMPORT_KIND, run_import_job

from musicseed_web.render import templates

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request) -> HTMLResponse:
    snapshot = get_dashboard_snapshot()
    return templates.TemplateResponse(request, "dashboard.html", {"snapshot": snapshot})


@router.get("/dashboard/status", response_class=HTMLResponse)
def dashboard_status(request: Request) -> HTMLResponse:
    snapshot = get_dashboard_snapshot()
    return templates.TemplateResponse(
        request, "_dashboard_status.html", {"snapshot": snapshot}
    )


@router.post("/dashboard/enrich", response_class=HTMLResponse)
def dashboard_enrich(
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


@router.post("/dashboard/sync", response_class=HTMLResponse)
def dashboard_sync(request: Request) -> HTMLResponse:
    try:
        jid = submit_job(IMPORT_KIND, run_import_job)
    except ValueError as e:
        return templates.TemplateResponse(
            request, "_job_error.html", {"error": str(e)}, status_code=409
        )
    job = get_job_progress(jid)
    return templates.TemplateResponse(request, "_job_progress.html", {"job": job})
