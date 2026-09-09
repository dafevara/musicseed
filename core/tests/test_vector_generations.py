"""Bounded vector commits are visible across independent runtime contexts."""

import subprocess
import sys

import numpy as np
import pytest
from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.db.models import RuntimeState, TrackVector
from musicseed.db.session import init_db
from musicseed.plex_db_source import ResolvedPlexDbs
from musicseed.services import jobs, sonic_vectors
from musicseed.sonic import SonicVectors


@pytest.fixture
def contexts(tmp_path, monkeypatch):
    cfg = Config.model_validate({"database": {"path": str(tmp_path / "local.db")}})
    writer, reader = MusicSeedContext(cfg), MusicSeedContext(cfg.model_copy(deep=True))
    init_db(writer)
    monkeypatch.setattr(sonic_vectors, "resolve_plex_dbs", lambda *_a, **_kw: ResolvedPlexDbs(
        tmp_path / "library.db", tmp_path / "blobs.db", "local",
    ))
    monkeypatch.setattr(sonic_vectors, "load_sonic_vectors", lambda **_kw: SonicVectors(
        list(range(1, 6)), np.ones((5, 50), dtype=np.float32),
    ))
    yield writer, reader
    writer.engine.dispose()
    reader.engine.dispose()


def test_each_committed_batch_refreshes_other_context_and_progress_can_write(contexts):
    writer, reader = contexts
    assert len(reader.sonic_vectors) == 0
    seen = []

    def progress(current, total, phase):
        if phase != "sonic vectors":
            return
        # Separate connection writes prove the vector transaction released its lock.
        active = jobs.get_active_jobs()[0]
        jobs.update_progress(active["id"], current, total, phase)
        seen.append((current, len(reader.sonic_vectors)))

    result = sonic_vectors.import_plex_sonic(context=writer, batch_size=2,
                                            progress_callback=progress)
    assert seen == [(2, 2), (4, 4), (5, 5)]
    assert result.imported == 5
    with reader.session() as session:
        assert session.get(RuntimeState, "sonic_generation").value == 3
    assert len(reader.sonic_vectors) == 5


def test_cancel_keeps_committed_batch_and_resume_is_idempotent(contexts):
    writer, reader = contexts

    def progress(current, total, phase):
        if current == 2:
            jobs.request_cancel(jobs.get_active_jobs()[0]["id"])

    first = sonic_vectors.import_plex_sonic(context=writer, batch_size=2,
                                           progress_callback=progress)
    assert first.imported == 2
    assert len(reader.sonic_vectors) == 2
    second = sonic_vectors.import_plex_sonic(context=writer, batch_size=2)
    assert second.imported == 3
    assert second.updated == 2
    with reader.session() as session:
        assert session.query(TrackVector).count() == 5
        states = [row.state for row in session.query(jobs.Job).order_by(jobs.Job.id)]
        assert states == [jobs.JobState.CANCELED, jobs.JobState.SUCCEEDED]
    assert len(reader.sonic_vectors) == 5


def test_error_after_commit_does_not_hide_data_or_retain_claim(contexts):
    writer, reader = contexts
    _ = reader.sonic_vectors

    def progress(current, _total, _phase):
        if current == 2:
            raise RuntimeError("fixture progress failure")

    with pytest.raises(RuntimeError, match="fixture progress"):
        sonic_vectors.import_plex_sonic(context=writer, batch_size=2, progress_callback=progress)
    assert len(reader.sonic_vectors) == 2
    with reader.session() as session:
        assert session.query(jobs.Job).one().state == jobs.JobState.FAILED
    assert sonic_vectors.import_plex_sonic(context=writer, batch_size=2).updated == 2


def test_import_in_another_process_invalidates_existing_cache(contexts):
    writer, reader = contexts
    assert len(reader.sonic_vectors) == 0
    code = """
import sys
import numpy as np
from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.services import sonic_vectors
from musicseed.sonic import SonicVectors
context = MusicSeedContext(Config.model_validate({
    "database": {"path": sys.argv[1]}, "plex": {"db_path": sys.argv[1] + ".fixture"},
}))
sonic_vectors.load_sonic_vectors = lambda **kw: SonicVectors([99], np.ones((1, 50)))
sonic_vectors.import_plex_sonic(context=context)
"""
    subprocess.run([sys.executable, "-c", code, writer.config.database.path],
                   check=True, capture_output=True, text=True, timeout=20)
    assert len(reader.sonic_vectors) == 1
    assert 99 in reader.sonic_vectors
