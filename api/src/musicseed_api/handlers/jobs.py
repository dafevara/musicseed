"""Job orchestration — submission, progress, cancellation, and deletion."""

from __future__ import annotations

from collections.abc import Callable

from musicseed.exceptions import JobConflictError, NotFoundError
from musicseed.services import jobs as jobs_service


def submit_job(kind: str, target: Callable[..., None], *args, **kwargs) -> int:
    """Submit a new job to the in-process runner. Returns the job id.

    Raises ``JobConflictError`` when a job of the same kind is already
    running or the concurrency pool is full.
    """
    return jobs_service.get_manager().submit(kind, target, *args, **kwargs)


def get_job_progress(job_id: int) -> dict | None:
    """Return the current snapshot of a job, or None if not found."""
    return jobs_service.get_job(job_id)


def cancel_job(job_id: int) -> None:
    """Request cancellation of a running job (cooperative)."""
    jobs_service.get_manager().request_cancel(job_id)


def delete_job(job_id: int) -> None:
    """Delete a completed job's history entry.

    Active jobs cannot be deleted — they must be canceled first and allowed
    to reach a terminal state.
    """
    job = jobs_service.get_job(job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id} not found")
    if job["state"] in {
        jobs_service.JobState.RUNNING,
        jobs_service.JobState.PENDING,
        jobs_service.JobState.CANCEL_REQUESTED,
    }:
        raise JobConflictError(
            f"Job {job_id} is still active — cancel it and wait for it to finish first."
        )
    jobs_service.delete_job(job_id)
