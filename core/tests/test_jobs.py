"""Tests for services.jobs — state transitions, progress, listing, recovery."""

import time

import pytest
from musicseed.config import Config, set_config
from musicseed.db.models import Job
from musicseed.db.session import get_session, init_db, reset_engine
from musicseed.exceptions import JobConflictError
from musicseed.services.jobs import (
    JobState,
    cancel_job,
    complete_job,
    create_job,
    fail_job,
    get_active_jobs,
    get_job,
    get_latest_job,
    reconcile_running_jobs,
    request_cancel,
    start_job,
    update_progress,
)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    import musicseed.services.jobs as jobs_module

    db_path = tmp_path / "musicseed.db"
    cfg = Config.model_validate({"database": {"path": str(db_path)}})
    set_config(cfg)
    reset_engine()
    init_db()
    jobs_module._manager = None
    yield
    jobs_module._manager = None
    reset_engine()


def test_create_job_starts_pending() -> None:
    jid = create_job("test")
    assert get_job(jid)["state"] == JobState.PENDING


def test_start_job_transitions_to_running() -> None:
    jid = create_job("test")
    start_job(jid)
    assert get_job(jid)["state"] == JobState.RUNNING


def test_complete_job() -> None:
    jid = create_job("test")
    start_job(jid)
    complete_job(jid)
    assert get_job(jid)["state"] == JobState.SUCCEEDED


def test_fail_job_stores_error() -> None:
    jid = create_job("test")
    start_job(jid)
    fail_job(jid, "something broke")
    j = get_job(jid)
    assert j["state"] == JobState.FAILED
    assert "something broke" in j["error_summary"]


def test_error_summary_truncated() -> None:
    jid = create_job("test")
    start_job(jid)
    fail_job(jid, "x" * 600)
    assert len(get_job(jid)["error_summary"]) == 500


def test_request_cancel_and_cancel() -> None:
    jid = create_job("test")
    start_job(jid)
    request_cancel(jid)
    assert get_job(jid)["state"] == JobState.CANCEL_REQUESTED
    cancel_job(jid)
    assert get_job(jid)["state"] == JobState.CANCELED


def test_update_progress() -> None:
    jid = create_job("test")
    update_progress(jid, 42, 100, "halfway")
    j = get_job(jid)
    assert j["progress_current"] == 42
    assert j["progress_total"] == 100
    assert j["checkpoint"] == "halfway"


def test_get_latest_job() -> None:
    create_job("import")
    time.sleep(0.01)
    create_job("import")
    latest = get_latest_job("import")
    assert latest is not None
    assert latest["kind"] == "import"


def test_get_active_jobs() -> None:
    create_job("run0")  # pending
    jid = create_job("run1")
    start_job(jid)
    active = get_active_jobs()
    assert len(active) >= 1


def test_reconcile_marks_running_as_interrupted() -> None:
    jid = create_job("doomed")
    start_job(jid)
    # Simulate a job owned by a now-dead process (pid that cannot be alive).
    with get_session() as session:
        session.get(Job, jid).pid = 2 ** 22
    reconcile_running_jobs()
    assert get_job(jid)["state"] == JobState.INTERRUPTED


def test_reconcile_leaves_own_running_job_alone() -> None:
    jid = create_job("mine")
    start_job(jid)
    reconcile_running_jobs()
    assert get_job(jid)["state"] == JobState.RUNNING


def test_jobs_persist_across_sessions() -> None:
    jid = create_job("persistent")
    start_job(jid)
    update_progress(jid, 3, 10, "check")
    # Force a new engine to simulate process restart
    reset_engine()
    j = get_job(jid)
    assert j["state"] == JobState.RUNNING
    assert j["progress_current"] == 3
    assert j["progress_total"] == 10


def test_non_existent_job_graceful() -> None:
    start_job(99999)
    complete_job(99999)
    fail_job(99999, "x")
    cancel_job(99999)
    request_cancel(99999)
    update_progress(99999, 1, 1)
    assert get_job(99999) is None


def test_cancel_stops_worker_cooperatively() -> None:
    """A worker polling should_cancel stops and the job lands in ``canceled``."""
    import threading

    from musicseed.services.jobs import get_manager

    manager = get_manager()
    calls: list[int] = []
    cancel_seen = threading.Event()

    def target(job_id: int) -> None:
        for i in range(20):
            calls.append(i)
            time.sleep(0.01)
            if manager.should_cancel(job_id):
                cancel_seen.set()
                return
        complete_job(job_id, "finished all batches")

    jid = manager.submit("test-cancel", target)

    deadline = time.time() + 5
    while len(calls) < 3 and time.time() < deadline:
        time.sleep(0.01)

    manager.request_cancel(jid)

    deadline = time.time() + 5
    state = get_job(jid)["state"]
    terminal = (JobState.CANCELED, JobState.SUCCEEDED, JobState.FAILED)
    while state not in terminal and time.time() < deadline:
        time.sleep(0.01)
        state = get_job(jid)["state"]

    assert cancel_seen.is_set()
    assert len(calls) < 20
    assert get_job(jid)["state"] == JobState.CANCELED


def test_submit_blocks_kind_owned_by_another_process() -> None:
    """A running job created outside this manager (another process) blocks submit."""
    from musicseed.services.jobs import get_manager

    jid = create_job("import")
    start_job(jid)  # running, but not in this manager's thread pool

    manager = get_manager()
    with pytest.raises(JobConflictError):
        manager.submit("import", lambda job_id: None)


def test_should_cancel_reads_database_state() -> None:
    """Cancellation is observed from the DB, not an in-memory flag."""
    from musicseed.services.jobs import JobManager

    jid = create_job("import")
    start_job(jid)

    fresh = JobManager()  # brand-new manager, no in-memory state
    assert fresh.should_cancel(jid) is False

    request_cancel(jid)  # DB write only
    assert fresh.should_cancel(jid) is True
