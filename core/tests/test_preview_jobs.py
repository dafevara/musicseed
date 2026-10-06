"""Preview jobs share recovery infrastructure without reserving the writer."""

import sqlite3
import threading

import pytest
from musicseed.config import Config
from musicseed.context import MusicSeedContext, reset_context, set_context
from musicseed.db.models import Job
from musicseed.db.session import ensure_schema, init_db
from musicseed.exceptions import JobConflictError, NotFoundError
from musicseed.services import jobs, preview_jobs
from musicseed.services.populate import PopulateResult
from sqlalchemy import event


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    context = MusicSeedContext(Config.model_validate({
        "database": {"path": str(tmp_path / "preview.db")},
    }))
    init_db(context)
    set_context(context)
    manager = jobs.JobManager()
    monkeypatch.setattr(jobs, "get_manager", lambda: manager)
    yield context, manager
    manager.shutdown()
    with manager._lock:
        threads = [thread for thread, _ in manager._active.values()]
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    reset_context()
    context.engine.dispose()


def join(manager):
    with manager._lock:
        threads = [thread for thread, _ in manager._active.values()]
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()


def test_preview_columns_migrate_an_existing_jobs_table_without_losing_history(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY, kind VARCHAR(50), state VARCHAR(50),
                progress_current INTEGER, progress_total INTEGER, checkpoint TEXT,
                error_summary TEXT, created_at DATETIME, updated_at DATETIME,
                started_at DATETIME, completed_at DATETIME
            );
            INSERT INTO jobs(id, kind, state) VALUES(1, 'import', 'succeeded');
        """)
    context = MusicSeedContext(Config.model_validate({"database": {"path": str(path)}}))
    try:
        ensure_schema(context)
        ensure_schema(context)
        with context.session() as session:
            legacy = session.get(Job, 1)
            assert legacy.state == "succeeded"
            assert legacy.result_payload is None
            assert legacy.request_key is None
        with sqlite3.connect(path) as connection:
            indexes = connection.execute("PRAGMA index_list(jobs)").fetchall()
            assert any(row[1] == "idx_jobs_request_key" and row[2] == 1 for row in indexes)
    finally:
        context.engine.dispose()


def test_preview_has_separate_slot_and_idempotent_submission(runtime):
    _, manager = runtime
    release = threading.Event()
    calls = []

    def work(job_id):
        calls.append(job_id)
        assert release.wait(5)

    try:
        writer = manager.submit("import", work)
        preview = manager.submit("playlist_preview", work, request_key="same-request")
        assert preview != writer
        assert manager.submit("playlist_preview", work, request_key="same-request") == preview
        with pytest.raises(JobConflictError):
            jobs.JobManager().submit("playlist_preview", work)
        with pytest.raises(JobConflictError):
            jobs.JobManager().submit("import", work)
        assert len(jobs.get_active_jobs()) == 2
    finally:
        release.set()
        join(manager)
    assert sorted(calls) == sorted([writer, preview])
    assert manager.submit("playlist_preview", work, request_key="same-request") == preview
    assert len(calls) == 2


@pytest.mark.parametrize("cancel", [False, True])
def test_payload_published_after_worker_exit_and_never_on_cancel(runtime, cancel):
    context, manager = runtime
    ready, release = threading.Event(), threading.Event()

    def work(job_id):
        jobs.complete_job(job_id, "ready", result_payload={"tracks": [1, 2, 3]})
        ready.set()
        assert release.wait(5)

    job_id = manager.submit("playlist_preview", work)
    try:
        assert ready.wait(5)
        with pytest.raises(JobConflictError):
            jobs.get_job_result(job_id, "playlist_preview")
        assert "result_payload" not in jobs.get_job(job_id)
        if cancel:
            jobs.request_cancel(job_id)
    finally:
        release.set()
        join(manager)
    if cancel:
        assert jobs.get_job(job_id)["state"] == "canceled"
        with context.session() as session:
            assert session.get(Job, job_id).result_payload is None
        with pytest.raises(JobConflictError):
            jobs.get_job_result(job_id, "playlist_preview")
    else:
        assert jobs.get_job_result(job_id, "playlist_preview") == {"tracks": [1, 2, 3]}
        statements = []
        event.listen(context.engine, "before_cursor_execute",
                     lambda _c, _cu, sql, _p, _ct, _m: statements.append(sql))
        jobs.get_job(job_id)
        jobs.list_jobs()
        assert not any("jobs.result_payload" in sql for sql in statements)
    with pytest.raises(NotFoundError):
        jobs.get_job_result(job_id, "import")


def test_preview_service_persists_inputs_progress_and_deduplicates(runtime, monkeypatch):
    _, manager = runtime
    calls = []

    def calculate(**options):
        calls.append(options)
        options["on_progress"](100, 100)
        assert not options["should_cancel"]()
        return PopulateResult(playlist_id=options["playlist_id"], playlist_name="Fixture",
                              playlist_track_count=4, matched_track_count=4, recommendations=[])

    monkeypatch.setattr(preview_jobs, "get_populate_recommendations", calculate)
    first = preview_jobs.start_preview("42", request_id="client-request", method="frequency")
    join(manager)
    repeated = preview_jobs.start_preview("42", request_id="client-request", method="frequency")
    assert repeated == first
    payload = preview_jobs.get_preview_result(first)
    assert payload.method == "frequency"
    assert payload.playlist_id == "42"
    assert jobs.get_job(first)["checkpoint"] == "Recommendations ready"
    changed = preview_jobs.start_preview("42", request_id="client-request", method="average")
    join(manager)
    assert changed != first
    assert len(calls) == 2


def test_preview_failure_is_terminal_and_sanitizes_unexpected_errors(runtime, monkeypatch):
    _, manager = runtime

    def fail(**_options):
        raise RuntimeError("private fixture details")

    monkeypatch.setattr(preview_jobs, "get_populate_recommendations", fail)
    job_id = preview_jobs.start_preview("42", request_id="failure")
    join(manager)
    job = jobs.get_job(job_id)
    assert job["state"] == "failed"
    assert "private fixture details" not in job["error_summary"]
    with pytest.raises(JobConflictError):
        preview_jobs.get_preview_result(job_id)
