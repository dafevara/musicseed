"""Job orchestration — submission, progress, and cancellation."""

from __future__ import annotations

from collections.abc import Callable

from musicseed.services.jobs import get_job, get_manager


def submit_job(kind: str, target: Callable[..., None], *args, **kwargs) -> int:
    """Submit a new job to the in-process runner. Returns the job id.

    Raises ``JobConflictError`` when a job of the same kind is already
    running or the concurrency pool is full.
    """
    return get_manager().submit(kind, target, *args, **kwargs)


def get_job_progress(job_id: int) -> dict | None:
    """Return the current snapshot of a job, or None if not found."""
    return get_job(job_id)


def cancel_job(job_id: int) -> None:
    """Request cancellation of a running job (cooperative)."""
    get_manager().request_cancel(job_id)
