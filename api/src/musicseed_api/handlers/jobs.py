"""Job orchestration — submission, progress, cancellation, and deletion."""

from __future__ import annotations

from collections.abc import Callable

from musicseed.exceptions import JobConflictError, NotFoundError
from musicseed.services import jobs as jobs_service


def submit_job(kind: str, target: Callable[..., None], *args, **kwargs) -> int:
    """Submit ``target`` to the in-process job runner; return the new job id.

    Entry point of the job-lifecycle story line: the ``JobManager`` creates a
    persisted job row, runs ``target`` in a daemon thread as
    ``target(job_id, *args, **kwargs)``, and reconciles its terminal state.

    Args:
        kind: job kind (see core ``JobKind``); only one active job per kind
            is allowed across processes sharing the database.
        target: blocking callable to run in the worker thread.
        *args: positional arguments forwarded to ``target`` after ``job_id``.
        **kwargs: keyword arguments forwarded to ``target``.

    Returns:
        The id of the newly created job row.

    Raises:
        JobConflictError: if a job of the same kind is already active, or the
            concurrency pool is full.
    """
    return jobs_service.get_manager().submit(kind, target, *args, **kwargs)


def get_job_progress(job_id: int) -> dict | None:
    """Return the current snapshot of a job.

    Args:
        job_id: id of the job row to read.

    Returns:
        The job's fields as a plain dict, or None for an unknown id.
    """
    return jobs_service.get_job(job_id)


def cancel_job(job_id: int) -> None:
    """Request cooperative cancellation of a running job.

    The worker polls for the request at safe checkpoints and winds itself
    down; nothing is interrupted forcibly.

    Args:
        job_id: id of the job to cancel.
    """
    jobs_service.get_manager().request_cancel(job_id)


def delete_job(job_id: int) -> None:
    """Delete a completed job's history entry.

    Active jobs cannot be deleted — they must be canceled first and allowed
    to reach a terminal state.

    Args:
        job_id: id of the job row to delete.

    Raises:
        NotFoundError: if the job does not exist.
        JobConflictError: if the job is still active.
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
