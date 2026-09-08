"""Persistent, in-process job abstraction for long-running MusicSeed work.

Every operation (create, start, update progress, complete, fail,
cancel-request) writes through a dedicated SQLAlchemy session. The
``JobManager`` singleton runs workers in daemon threads — no external
queue, no Redis, no containers. On first access it reconciles jobs
left in any nonterminal state by a dead process into ``interrupted``.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from enum import StrEnum
from functools import wraps
from inspect import signature

from sqlalchemy import case, text, update

from musicseed.context import MusicSeedContext, get_context, use_context
from musicseed.db.models import ImportState, Job
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


ACTIVE_STATES = (JobState.PENDING, JobState.RUNNING, JobState.CANCEL_REQUESTED)
_configuration_lock = threading.RLock()
_worker_job: ContextVar[tuple[str, int] | None] = ContextVar("musicseed_worker_job", default=None)
_managed_worker: ContextVar[bool] = ContextVar("musicseed_managed_worker", default=False)
_requested_result: ContextVar[str] = ContextVar("musicseed_requested_result", default="")
_requested_failure: ContextVar[str | None] = ContextVar("musicseed_requested_failure", default=None)


@contextmanager
def configuration_change():
    """Serialize config replacement with submissions; never initialize a database."""
    with _configuration_lock:
        path = get_context().config.database.path_expanded
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema")}
                if "jobs" in tables and conn.execute(
                    "SELECT 1 FROM jobs WHERE state IN (?, ?, ?) LIMIT 1", ACTIVE_STATES
                ).fetchone():
                    raise JobConflictError(
                        "Wait for active jobs to finish before changing settings."
                    )
        yield


def current_job_id() -> int | None:
    """The operation-bound job ID, if called from a claimed writer."""
    owned = _worker_job.get()
    return owned[1] if owned else None


def _claim_job(kind: str, context: MusicSeedContext) -> int:
    ensure_schema(context)
    reconcile_running_jobs()
    with context.session() as session:
        # Atomic across processes: reserve SQLite's writer before checking.
        session.execute(text("BEGIN IMMEDIATE"))
        if session.query(Job).filter(Job.state.in_(ACTIVE_STATES)).first():
            raise JobConflictError("A job is already active; wait for it to finish.")
        job = Job(kind=kind, state=JobState.PENDING, pid=os.getpid())
        session.add(job)
        session.flush()
        return job.id


def exclusive_writer(kind: str):
    """Use the same persisted writer claim for synchronous CLI/service imports.

    A service called inside a managed worker reuses its claim. There is no
    separate queue or scheduler; the SQLite job row is the reservation.
    """
    def decorate(function):
        parameters = signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = parameters.bind(*args, **kwargs)
            context = bound.arguments.get("context") or get_context()
            owned = _worker_job.get()
            if owned is not None:
                if owned[0] != context.config.database.url:
                    raise JobConflictError("A worker cannot change its database.")
                job_id = owned[1]
            else:
                with _configuration_lock:
                    context = MusicSeedContext(context.config.model_copy(deep=True))
                    with use_context(context):
                        job_id = _claim_job(kind, context)
            with use_context(context):
                bound.arguments["context"] = context
                original_cancel = bound.arguments.get("should_cancel")
                saw_cancel = False

                def should_cancel():
                    nonlocal saw_cancel
                    saw_cancel = bool(saw_cancel or (original_cancel and original_cancel())
                                      or get_job(job_id)["state"] == JobState.CANCEL_REQUESTED)
                    return saw_cancel

                bound.arguments["should_cancel"] = should_cancel
                token = _worker_job.set((context.config.database.url, job_id))
                try:
                    if owned is None:
                        start_job(job_id)
                    result = function(*bound.args, **bound.kwargs)
                    if saw_cancel or get_job(job_id)["state"] == JobState.CANCEL_REQUESTED:
                        cancel_job(job_id)
                    elif owned is None:
                        complete_job(job_id)
                    return result
                except BaseException as error:
                    if owned is None:
                        if isinstance(error, KeyboardInterrupt):
                            cancel_job(job_id)
                        else:
                            fail_job(job_id, f"{type(error).__name__}: {error}")
                    raise
                finally:
                    _worker_job.reset(token)
                    if owned is None:
                        context.engine.dispose()
        return wrapped
    return decorate


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
        session.execute(update(Job).where(
            Job.id == job_id, Job.state == JobState.PENDING,
        ).values(state=JobState.RUNNING, started_at=_now()))


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
            when non-empty. Managed targets defer completion until they return.
    """
    if _managed_worker.get() and _worker_job.get()[1] == job_id:
        _requested_result.set(result_summary)
        return
    with get_session() as session:
        session.execute(update(Job).where(Job.id == job_id, Job.state.in_(ACTIVE_STATES)).values(
            state=case((Job.state == JobState.CANCEL_REQUESTED, JobState.CANCELED),
                       else_=JobState.SUCCEEDED),
            completed_at=_now(), result_summary=result_summary or None,
        ))


def fail_job(job_id: int, error_summary: str) -> None:
    """Mark a job ``failed`` and stamp its completion time.

    Args:
        job_id: id of the job row to update. Unknown ids are ignored.
        error_summary: failure description, truncated to 500 characters.
    """
    if _managed_worker.get() and current_job_id() == job_id:
        _requested_failure.set(error_summary)
        return
    with get_session() as session:
        session.execute(update(Job).where(Job.id == job_id, Job.state.in_(ACTIVE_STATES)).values(
            state=case((Job.state == JobState.CANCEL_REQUESTED, JobState.CANCELED),
                       else_=JobState.FAILED),
            error_summary=(error_summary or "")[:500], completed_at=_now(),
        ))


def request_cancel(job_id: int) -> None:
    """Set a job's state to ``cancel_requested`` (cooperative cancellation).

    The worker still has to observe the request (via
    ``JobManager.should_cancel``) and wind itself down; nothing is interrupted
    forcibly.

    Args:
        job_id: id of the job row to update. Unknown ids are ignored.
    """
    with get_session() as session:
        session.execute(update(Job).where(
            Job.id == job_id, Job.state.in_((JobState.PENDING, JobState.RUNNING)),
        ).values(state=JobState.CANCEL_REQUESTED))


def cancel_job(job_id: int) -> None:
    """Mark canceled, retaining a managed worker's claim until its target exits."""
    if _managed_worker.get() and _worker_job.get()[1] == job_id:
        request_cancel(job_id)
        return
    with get_session() as session:
        session.execute(update(Job).where(Job.id == job_id, Job.state.in_(ACTIVE_STATES)).values(
            state=JobState.CANCELED, completed_at=_now(),
        ))


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
        if job.state in ACTIVE_STATES:
            raise JobConflictError("Cancel the job and wait for it to stop before deleting it.")
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
    """Return pending/running/cancel-requested jobs; all still reserve the writer.

    Returns:
        Job snapshots as plain dicts.
    """
    with get_session() as session:
        ensure_schema()
        jobs = (
            session.query(Job)
            .filter(Job.state.in_(ACTIVE_STATES))
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
    """Reconcile every nonterminal state owned by a dead process.

    Pending jobs and cancellation requests can also survive a crash. Live
    owners are left alone, including other API/CLI processes.
    """
    with get_session() as session:
        ensure_schema()
        orphans = (
            session.query(Job)
            .filter(Job.state.in_(ACTIVE_STATES))
            .all()
        )
        for job in orphans:
            if not _pid_alive(job.pid):
                job.state = JobState.INTERRUPTED
                job.completed_at = _now()
                session.query(ImportState).filter(
                    ImportState.job_id == job.id, ImportState.state == "running",
                ).update({"state": "interrupted"})


# ------------------------------------------------------------------ manager


class JobManager:
    """In-process runner with a bounded concurrency pool.

    Workers are daemon threads. Job state lives in the ``jobs`` table (shared
    across processes); the in-memory bookkeeping only tracks this process's
    threads and concurrency. Cancel is cooperative (``should_cancel`` reads the
    DB — workers poll it at safe checkpoints).
    """

    def __init__(self, max_concurrent: int = 1) -> None:
        """Create a manager that runs at most ``max_concurrent`` jobs at once.

        Args:
            max_concurrent: maximum number of worker threads allowed to be
                active simultaneously; further submissions are rejected.
        """
        self._max = max_concurrent
        self._active: dict[tuple[str, int], tuple[threading.Thread, MusicSeedContext]] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, target: Callable[..., None], *args, **kwargs) -> int:
        """Create a job and run ``target`` for it in a daemon thread.

        The target is called as ``target(job_id, *args, **kwargs)`` — the job
        id is always the first positional argument.

        Args:
            kind: job kind (see ``JobKind``); only one active job of any kind
                is allowed across all processes sharing the database.
            target: blocking callable to run in the worker thread.
            *args (Any): extra positional arguments forwarded to ``target``.
            **kwargs (Any): keyword arguments forwarded to ``target``.

        Returns:
            The id of the newly created job row.

        Raises:
            JobConflictError: if a job of the same kind is already active, or
                the concurrency pool is full.
        """
        with _configuration_lock, self._lock:
            if len(self._active) >= self._max:
                raise JobConflictError("An operation is still running; wait for it to finish.")
            # A deep copy isolates both the config and all legacy callback lookups.
            context = MusicSeedContext(get_context().config.model_copy(deep=True))
            with use_context(context):
                job_id = _claim_job(kind, context)
            key = (context.config.database.url, job_id)
            thread = threading.Thread(
                target=self._worker,
                args=(key, context, job_id, target, args, kwargs),
                daemon=True,
            )
            self._active[key] = (thread, context)
            try:
                thread.start()
            except Exception:
                self._active.pop(key, None)
                with use_context(context):
                    fail_job(job_id, "Could not start worker thread")
                raise
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
            active = list(self._active.items())
        for (_url, jid), (_thread, context) in active:
            with use_context(context):
                request_cancel(jid)

    def _worker(self, key, context, job_id: int, target: Callable, args, kwargs) -> None:
        with use_context(context):
            token = _worker_job.set(key)
            try:
                start_job(job_id)
                managed = _managed_worker.set(True)
                try:
                    if not self.should_cancel(job_id):
                        target(job_id, *args, **kwargs)
                finally:
                    _managed_worker.reset(managed)
                job = get_job(job_id)
                if job and job["state"] == JobState.CANCEL_REQUESTED:
                    cancel_job(job_id)
                elif job and job["state"] in ACTIVE_STATES:
                    failure = _requested_failure.get()
                    if failure is not None:
                        fail_job(job_id, failure)
                    else:
                        complete_job(job_id, _requested_result.get())
            except BaseException as e:
                if isinstance(e, KeyboardInterrupt) or self.should_cancel(job_id):
                    cancel_job(job_id)
                else:
                    fail_job(job_id, f"{type(e).__name__}: {e}")
            finally:
                _worker_job.reset(token)
                context.engine.dispose()
                with self._lock:
                    self._active.pop(key, None)


# Module-level singleton (lazy, reconciled on first access)
_manager: JobManager | None = None


def get_manager() -> JobManager:
    """Return the module-level ``JobManager`` singleton, creating it lazily.

    On first access, nonterminal jobs owned by dead processes are reconciled
    to ``interrupted`` before the manager is returned.

    Returns:
        The shared ``JobManager`` instance.
    """
    global _manager
    if _manager is None:
        reconcile_running_jobs()
        _manager = JobManager()
    return _manager
