"""Persistent, in-process job abstraction for long-running MusicSeed work.

Every operation (create, start, update progress, complete, fail,
cancel-request) writes through a dedicated SQLAlchemy session. The
``JobManager`` singleton runs workers in daemon threads — no external
queue, no Redis, no containers. On first access it reconciles any jobs
left in a ``running`` state from a prior process into ``interrupted``.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from musicseed.db.models import Job
from musicseed.db.session import ensure_schema, get_session
from musicseed.exceptions import JobConflictError


class JobKind(StrEnum):
    IMPORT = "import"
    ENRICH = "enrich"


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    CANCEL_REQUESTED = "cancel_requested"
    INTERRUPTED = "interrupted"


# ------------------------------------------------------------------ helpers


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "progress_phases": job.progress_phases,
        "checkpoint": job.checkpoint,
        "error_summary": job.error_summary,
        "result_summary": job.result_summary,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


# ------------------------------------------------------------------ db ops


def create_job(kind: str) -> int:
    """Insert a new ``pending`` job and return its id."""
    with get_session() as session:
        ensure_schema()
        job = Job(kind=kind, state=JobState.PENDING, pid=os.getpid())
        session.add(job)
        session.flush()
        return job.id


def start_job(job_id: int) -> None:
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.RUNNING
        job.started_at = _now()


def update_progress(
    job_id: int,
    current: int,
    total: int = 0,
    checkpoint: str = "",
    phases: dict | None = None,
) -> None:
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.progress_current = current
        job.progress_total = total
        if checkpoint:
            job.checkpoint = checkpoint
        if phases is not None:
            job.progress_phases = phases


def complete_job(job_id: int, result_summary: str = "") -> None:
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.SUCCEEDED
        job.completed_at = _now()
        if result_summary:
            job.result_summary = result_summary


def fail_job(job_id: int, error_summary: str) -> None:
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.FAILED
        job.error_summary = (error_summary or "")[:500]
        job.completed_at = _now()


def request_cancel(job_id: int) -> None:
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.CANCEL_REQUESTED


def cancel_job(job_id: int) -> None:
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.CANCELED
        job.completed_at = _now()


def get_job(job_id: int) -> dict | None:
    with get_session() as session:
        ensure_schema()
        job = session.get(Job, job_id)
        return _job_to_dict(job) if job else None


def delete_job(job_id: int) -> bool:
    """Delete a job row by id. Returns True if a row was deleted."""
    with get_session() as session:
        ensure_schema()
        job = session.get(Job, job_id)
        if job is None:
            return False
        session.delete(job)
        return True


def list_jobs(limit: int = 20) -> list[dict]:
    with get_session() as session:
        ensure_schema()
        jobs = (
            session.query(Job)
            .order_by(Job.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_job_to_dict(j) for j in jobs]


def get_latest_job(kind: str) -> dict | None:
    with get_session() as session:
        ensure_schema()
        job = (
            session.query(Job)
            .filter(Job.kind == kind)
            .order_by(Job.created_at.desc())
            .first()
        )
        return _job_to_dict(job) if job else None


def get_active_jobs() -> list[dict]:
    with get_session() as session:
        ensure_schema()
        jobs = (
            session.query(Job)
            .filter(Job.state.in_([JobState.RUNNING, JobState.PENDING]))
            .all()
        )
        return [_job_to_dict(j) for j in jobs]


def _pid_alive(pid: int | None) -> bool:
    """Best-effort liveness check for a recorded owner pid (POSIX only)."""
    if pid is None:
        return False  # legacy row, owner unknown — treat as dead
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists but not ours (e.g. PermissionError) — treat as alive
    return True


def reconcile_running_jobs() -> None:
    """Mark ``running`` jobs from dead processes as ``interrupted``.

    A job is only interrupted when its recorded owner pid is no longer alive,
    so starting one process while another genuinely runs a job leaves that job
    untouched.
    """
    with get_session() as session:
        ensure_schema()
        orphans = (
            session.query(Job)
            .filter(Job.state == JobState.RUNNING)
            .all()
        )
        for job in orphans:
            if not _pid_alive(job.pid):
                job.state = JobState.INTERRUPTED


# ------------------------------------------------------------------ manager


class JobManager:
    """In-process runner with a bounded concurrency pool.

    Workers are daemon threads. Job state lives in the ``jobs`` table (shared
    across processes); the in-memory bookkeeping only tracks this process's
    threads and concurrency. Cancel is cooperative (``should_cancel`` reads the
    DB — workers poll it at safe checkpoints).
    """

    def __init__(self, max_concurrent: int = 2) -> None:
        self._max = max_concurrent
        self._active: dict[int, threading.Thread] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, target: Callable[..., None], *args, **kwargs) -> int:
        active_kinds = {j["kind"] for j in get_active_jobs()}
        if kind in active_kinds:
            raise JobConflictError(
                f"A {kind} job is already running — wait for it to finish."
            )
        with self._lock:
            if len(self._active) >= self._max:
                raise JobConflictError(
                    f"Already at the maximum of {self._max} concurrent jobs."
                )

        job_id = create_job(kind)
        thread = threading.Thread(
            target=self._worker,
            args=(job_id, kind, target, args, kwargs),
            daemon=True,
        )
        with self._lock:
            self._active[job_id] = thread
        thread.start()
        return job_id

    def request_cancel(self, job_id: int) -> None:
        request_cancel(job_id)

    def should_cancel(self, job_id: int) -> bool:
        job = get_job(job_id)
        return job is not None and job["state"] == JobState.CANCEL_REQUESTED

    def shutdown(self) -> None:
        """Request cancellation of every active job (threads are daemons)."""
        with self._lock:
            job_ids = list(self._active.keys())
        for jid in job_ids:
            request_cancel(jid)

    def _worker(self, job_id: int, kind: str, target: Callable, args, kwargs) -> None:
        try:
            start_job(job_id)
            target(job_id, *args, **kwargs)
            job = get_job(job_id)
            if job and job["state"] == JobState.CANCEL_REQUESTED:
                cancel_job(job_id)
            elif job and job["state"] != JobState.SUCCEEDED:
                complete_job(job_id)
        except Exception as e:
            if self.should_cancel(job_id):
                cancel_job(job_id)
            else:
                fail_job(job_id, f"{type(e).__name__}: {e}")
        finally:
            with self._lock:
                self._active.pop(job_id, None)


# Module-level singleton (lazy, reconciled on first access)
_manager: JobManager | None = None


def get_manager() -> JobManager:
    global _manager
    if _manager is None:
        reconcile_running_jobs()
        _manager = JobManager()
    return _manager
