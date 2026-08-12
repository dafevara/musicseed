"""JSON endpoints for job progress and cancellation."""

from __future__ import annotations

from fastapi import APIRouter
from musicseed.exceptions import NotFoundError

from musicseed_api.handlers.jobs import cancel_job, get_job_progress

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}")
def job_status(job_id: int) -> dict:
    job = get_job_progress(job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id} not found")
    return job


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: int) -> dict:
    job = get_job_progress(job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id} not found")
    cancel_job(job_id)
    return get_job_progress(job_id) or {}
