"""Jobs keep their submission context and one writer until their worker exits."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from musicseed.config import Config, get_config
from musicseed.context import MusicSeedContext, reset_context, set_context, use_context
from musicseed.db.models import Track
from musicseed.db.session import get_session, init_db
from musicseed.services import jobs
from musicseed.services.jobs import JobConflictError, JobManager, JobState


@pytest.fixture
def context(tmp_path):
    ctx = MusicSeedContext(Config.model_validate({"database": {"path": str(tmp_path / "a.db")}}))
    init_db(ctx)
    set_context(ctx)
    yield ctx
    reset_context()
    ctx.engine.dispose()


def _join(manager):
    with manager._lock:
        threads = [thread for thread, _ctx in manager._active.values()]
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_work_and_callbacks_keep_database_a_after_default_switch(context, tmp_path):
    other = MusicSeedContext(Config.model_validate({"database": {"path": str(tmp_path / "b.db")}}))
    init_db(other)
    manager = JobManager()
    started, release = threading.Event(), threading.Event()

    def target(job_id):
        started.set()
        assert release.wait(5)
        assert get_config().database.path == context.config.database.path
        with get_session() as session:
            session.add(Track(plex_id=42, title="Bound to A"))
        jobs.update_progress(job_id, 1, 1, "written in A")

    job_id = manager.submit("import", target)
    try:
        assert started.wait(5)
        set_context(other)
        assert jobs.create_job("other") == job_id  # same ID in a different database
    finally:
        release.set()
        _join(manager)
    with use_context(context):
        assert jobs.get_job(job_id)["state"] == JobState.SUCCEEDED
        assert jobs.get_job(job_id)["progress_current"] == 1
    with other.session() as session:
        assert session.query(Track).count() == 0
    with context.session() as session:
        assert session.query(Track).one().title == "Bound to A"
    assert jobs.get_job(job_id)["state"] == JobState.PENDING
    other.engine.dispose()


def test_cancel_requested_reserves_writer_and_blocks_settings_and_deletion(context):
    started, release = threading.Event(), threading.Event()
    manager = JobManager()

    def target(job_id):
        started.set()
        assert release.wait(5)
        jobs.complete_job(job_id)  # cannot override a cancellation request

    job_id = manager.submit("import", target)
    try:
        assert started.wait(5)
        jobs.request_cancel(job_id)
        assert jobs.get_active_jobs()[0]["state"] == JobState.CANCEL_REQUESTED
        with pytest.raises(JobConflictError):
            JobManager().submit("sonic_import", lambda _id: None)
        with pytest.raises(JobConflictError), jobs.configuration_change():
            pytest.fail("configuration change must be rejected")
        with pytest.raises(JobConflictError):
            jobs.delete_job(job_id)
    finally:
        release.set()
        _join(manager)
    assert jobs.get_job(job_id)["state"] == JobState.CANCELED
    with jobs.configuration_change():
        pass
    assert jobs.delete_job(job_id)


def test_concurrent_submissions_only_claim_one_writer(context):
    release = threading.Event()
    managers = [JobManager(), JobManager()]
    barrier = threading.Barrier(2)

    def submit(manager):
        barrier.wait(timeout=5)
        try:
            return manager.submit("import", lambda _id: release.wait(5))
        except JobConflictError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(submit, managers))
        assert sum(claim is not None for claim in claims) == 1
        assert len(jobs.get_active_jobs()) == 1
    finally:
        release.set()
        for manager in managers:
            _join(manager)


@pytest.mark.parametrize("state", [JobState.PENDING, JobState.RUNNING, JobState.CANCEL_REQUESTED])
def test_recovery_reconciles_all_dead_owner_states(context, monkeypatch, state):
    job_id = jobs.create_job("import")
    with context.session() as session:
        session.get(jobs.Job, job_id).state = state
        session.add(jobs.ImportState(source_key="fixture", job_id=job_id, state="running"))
    monkeypatch.setattr(jobs, "_pid_alive", lambda _pid: False)
    jobs.reconcile_running_jobs()
    assert jobs.get_job(job_id)["state"] == JobState.INTERRUPTED
    assert jobs.get_job(job_id)["completed_at"] is not None
    with context.session() as session:
        assert session.get(jobs.ImportState, "fixture").state == "interrupted"


def test_thread_start_failure_releases_persisted_claim(context, monkeypatch):
    def fail(_thread):
        raise RuntimeError("fixture launch failure")

    monkeypatch.setattr(threading.Thread, "start", fail)
    manager = JobManager()
    with pytest.raises(RuntimeError, match="fixture launch"):
        manager.submit("import", lambda _id: None)
    assert jobs.get_active_jobs() == []
    assert jobs.list_jobs()[0]["state"] == JobState.FAILED
    assert not manager._active


@pytest.mark.parametrize("outcome", ["complete", "cancel", "fail"])
def test_target_terminal_requests_do_not_release_writer_early(context, outcome):
    manager = JobManager()
    requested, release = threading.Event(), threading.Event()

    def target(job_id):
        if outcome == "complete":
            jobs.complete_job(job_id, "fixture result")
        elif outcome == "cancel":
            jobs.cancel_job(job_id)
        else:
            jobs.fail_job(job_id, "fixture failure")
        requested.set()
        assert release.wait(5)

    job_id = manager.submit("import", target)
    try:
        assert requested.wait(5)
        assert jobs.get_job(job_id)["state"] in jobs.ACTIVE_STATES
        with pytest.raises(JobConflictError):
            JobManager().submit("sonic_import", lambda _id: None)
    finally:
        release.set()
        _join(manager)
    expected = {"complete": "succeeded", "cancel": "canceled", "fail": "failed"}
    assert jobs.get_job(job_id)["state"] == expected[outcome]


def test_cancellation_racing_completion_always_ends_terminal(context):
    for _ in range(8):
        job_id = jobs.create_job("import")
        jobs.start_job(job_id)
        barrier = threading.Barrier(2)

        def finish():
            barrier.wait(timeout=5)
            jobs.complete_job(job_id)

        def cancel():
            barrier.wait(timeout=5)
            jobs.request_cancel(job_id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(finish), executor.submit(cancel)]
            for future in futures:
                future.result(timeout=5)
        assert jobs.get_job(job_id)["state"] in (JobState.SUCCEEDED, JobState.CANCELED)


@pytest.mark.parametrize("error,state", [(KeyboardInterrupt, "canceled"), (SystemExit, "failed")])
def test_abrupt_target_exit_does_not_leave_live_pid_orphan(context, error, state):
    manager = JobManager()

    def target(_job_id):
        raise error("fixture abrupt exit")

    job_id = manager.submit("import", target)
    _join(manager)
    assert jobs.get_job(job_id)["state"] == state
    assert not jobs.get_active_jobs()
