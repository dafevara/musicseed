"""Settings updates are rejected during work and never mutate existing contexts."""

import threading

import pytest
from musicseed.config import get_config
from musicseed.context import get_context
from musicseed.db.session import init_db
from musicseed.exceptions import JobConflictError
from musicseed.services import jobs
from musicseed_api.handlers import discovery


def test_settings_during_job_are_rejected_then_replace_a_copy(tmp_path, monkeypatch):
    init_db()
    original_config = get_config()
    original_context = get_context()
    saved = []
    monkeypatch.setattr(discovery, "save_config", saved.append)
    manager = jobs.JobManager()
    started, release = threading.Event(), threading.Event()

    def target(_job_id):
        started.set()
        assert release.wait(5)

    manager.submit("import", target)
    try:
        assert started.wait(5)
        with pytest.raises(JobConflictError):
            discovery.save_config_overrides(
                musicseed_db_path=str(tmp_path / "other.db"), plex_library="Other",
            )
        assert get_config() is original_config
        assert get_context() is original_context
        assert not saved
    finally:
        with manager._lock:
            threads = [thread for thread, _context in manager._active.values()]
        release.set()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()

    discovery.save_config_overrides(
        musicseed_db_path=str(tmp_path / "other.db"), plex_library="Other",
    )
    assert saved[0] is get_config()
    assert get_context() is not original_context
    assert original_config.plex.library == "Music"
    assert original_config.database.path != get_config().database.path
    assert not (tmp_path / "other.db").exists()


def test_failed_config_save_does_not_change_running_configuration(monkeypatch):
    original_config, original_context = get_config(), get_context()

    def fail(_config):
        raise OSError("fixture disk failure")

    monkeypatch.setattr(discovery, "save_config", fail)
    with pytest.raises(OSError, match="fixture disk"):
        discovery.save_config_overrides(plex_library="Not Saved")
    assert get_config() is original_config
    assert get_context() is original_context
    assert original_config.plex.library == "Music"


def test_explicit_local_path_clears_ssh_consistently_with_discovery(tmp_path, monkeypatch):
    original = get_config()
    original.plex.db_ssh_target = "user@fixture:/remote"
    monkeypatch.setattr(discovery, "save_config", lambda _cfg: None)
    discovery.save_config_overrides(plex_db_path=str(tmp_path / "local-plex.db"))
    assert get_config().plex.db_ssh_target == ""
    assert get_config().plex.db_path == str(tmp_path / "local-plex.db")
    assert original.plex.db_ssh_target == "user@fixture:/remote"
