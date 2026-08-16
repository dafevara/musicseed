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
    """The kinds of long-running work the job system tracks."""

    IMPORT = "import"
    ENRICH = "enrich"


class JobState(StrEnum):
    """Lifecycle states of a job row."""

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
    """Mark a job ``running`` and stamp its start time.

    Args:
        job_id: id of the job row to update. Unknown ids are ignored.
    """
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
    """Record progress for a running job.

    Args:
        job_id: id of the job row to update. Unknown ids are ignored.
        current: units of work completed so far.
        total: total units of work expected (0 when unknown).
        checkpoint: human-readable status line; only stored when non-empty.
        phases: per-phase ``{"current", "total"}`` snapshot for multi-phase
            jobs; only stored when not None.
    """
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
    """Mark a job ``succeeded`` and stamp its completion time.

    Args:
        job_id: id of the job row to update. Unknown ids are ignored.
        result_summary: optional JSON-serialized outcome summary; only stored
            when non-empty.
    """
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.SUCCEEDED
        job.completed_at = _now()
        if result_summary:
            job.result_summary = result_summary


def fail_job(job_id: int, error_summary: str) -> None:
    """Mark a job ``failed`` and stamp its completion time.

    Args:
        job_id: id of the job row to update. Unknown ids are ignored.
        error_summary: failure description, truncated to 500 characters.
    """
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.FAILED
        job.error_summary = (error_summary or "")[:500]
        job.completed_at = _now()


def request_cancel(job_id: int) -> None:
    """Set a job's state to ``cancel_requested`` (cooperative cancellation).

    The worker still has to observe the request (via
    ``JobManager.should_cancel``) and wind itself down; nothing is interrupted
    forcibly.

    Args:
        job_id: id of the job row to update. Unknown ids are ignored.
    """
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.CANCEL_REQUESTED


def cancel_job(job_id: int) -> None:
    """Mark a job ``canceled`` and stamp its completion time.

    Args:
        job_id: id of the job row to update. Unknown ids are ignored.
    """
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.state = JobState.CANCELED
        job.completed_at = _now()


def get_job(job_id: int) -> dict | None:
    """Return a snapshot of one job, or None when it does not exist.

    Args:
        job_id: id of the job row to read.

    Returns:
        The job's fields as a plain dict, or None for an unknown id.
    """
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
    """Return the most recent jobs, newest first.

    Args:
        limit: maximum number of jobs to return.

    Returns:
        Job snapshots as plain dicts, ordered by creation time descending.
    """
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
    """Return the most recent job of a given kind, or None.

    Args:
        kind: job kind to filter on (see ``JobKind``).

    Returns:
        The newest matching job snapshot as a plain dict, or None when no
        job of that kind exists.
    """
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
    """Return all jobs in a non-terminal state (``running`` or ``pending``).

    Returns:
        Job snapshots as plain dicts.
    """
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
        """Create a manager that runs at most ``max_concurrent`` jobs at once.

        Args:
            max_concurrent: maximum number of worker threads allowed to be
                active simultaneously; further submissions are rejected.
        """
        self._max = max_concurrent
        self._active: dict[int, threading.Thread] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, target: Callable[..., None], *args, **kwargs) -> int:
        """Create a job and run ``target`` for it in a daemon thread.

        The target is called as ``target(job_id, *args, **kwargs)`` — the job
        id is always the first positional argument.

        Args:
            kind: job kind (see ``JobKind``); only one active job per kind is
                allowed across all processes sharing the database.
            target: blocking callable to run in the worker thread.
            *args: extra positional arguments forwarded to ``target``.
            **kwargs: keyword arguments forwarded to ``target``.

        Returns:
            The id of the newly created job row.

        Raises:
            JobConflictError: if a job of the same kind is already active, or
                the concurrency pool is full.
        """
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
        """Ask a job to stop (cooperative; see ``request_cancel``).

        Args:
            job_id: id of the job to cancel.
        """
        request_cancel(job_id)

    def should_cancel(self, job_id: int) -> bool:
        """Return True when cancellation has been requested for a job.

        Workers poll this at safe checkpoints and then wind down on their own.

        Args:
            job_id: id of the job to check.

        Returns:
            True if the job exists and its state is ``cancel_requested``.
        """
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
    """Return the module-level ``JobManager`` singleton, creating it lazily.

    On first access, jobs left ``running`` by dead processes are reconciled
    to ``interrupted`` before the manager is returned.

    Returns:
        The shared ``JobManager`` instance.
    """
    global _manager
    if _manager is None:
        reconcile_running_jobs()
        _manager = JobManager()
    return _manager
