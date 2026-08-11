"""JSON endpoints for library status and import."""

from __future__ import annotations

from fastapi import APIRouter

from musicseed_api.handlers.jobs import submit_job
from musicseed_api.handlers.library import IMPORT_KIND, get_library_status, run_import_job

router = APIRouter(tags=["library"])


@router.get("/library/status")
def library_status() -> dict:
    return get_library_status().model_dump()


@router.post("/library/import")
def start_import() -> dict:
    job_id = submit_job(IMPORT_KIND, run_import_job)
    return {"job_id": job_id}
