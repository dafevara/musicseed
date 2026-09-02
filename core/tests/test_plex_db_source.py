"""Tests for musicseed.plex_db_source — local passthrough + SFTP fetch."""

from pathlib import Path

import musicseed.plex_db_source as pds
import pytest
from musicseed.config import Config
from musicseed.exceptions import NotFoundError


def _config(tmp_path, db_ssh_target: str = "") -> Config:
    return Config.model_validate({
        "database": {"path": str(tmp_path / "ms" / "musicseed.db")},
        "plex": {
            "db_path": str(tmp_path / "plex" / "com.plexapp.plugins.library.db"),
            "db_ssh_target": db_ssh_target,
        },
    })


class _Sftp:
    def __init__(self, calls: list[str], *, fail_library: bool = False):
        self.calls = calls
        self.fail_library = fail_library

    def get(self, remote: str, local: str) -> None:
        self.calls.append(remote)
        if self.fail_library and remote.endswith("com.plexapp.plugins.library.db"):
            raise FileNotFoundError(remote)
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_bytes(pds.SQLITE_HEADER + b"rest")

    def stat(self, path: str):
        raise FileNotFoundError(path)

    def close(self) -> None:
        pass


class _Client:
    def __init__(self, sftp: _Sftp):
        self._sftp = sftp

    def open_sftp(self) -> _Sftp:
        return self._sftp

    def close(self) -> None:
        pass


def test_parse_ssh_target():
    assert pds.parse_ssh_target("user@nas.local:/volume1/Plex") == (
        "user", "nas.local", "/volume1/Plex",
    )
    assert pds.parse_ssh_target("nas:/a/b/") == (None, "nas", "/a/b")
    with pytest.raises(NotFoundError):
        pds.parse_ssh_target("missing-colon")


def test_local_source_returns_configured_paths(tmp_path):
    cfg = _config(tmp_path)
    resolved = pds.resolve_plex_dbs(cfg)
    assert resolved.source == "local"
    assert resolved.library_db == cfg.plex.db_path_expanded
    assert resolved.blobs_db == cfg.plex.blobs_db_path_expanded


def test_ssh_source_fetches_and_caches(monkeypatch, tmp_path):
    cfg = _config(tmp_path, db_ssh_target="user@nas.local:/volume1/Plex/Databases")
    cache = tmp_path / "cache"
    monkeypatch.setattr(pds, "_cache_dir", lambda target: cache)

    calls: list[str] = []
    monkeypatch.setattr(
        pds, "_open_ssh", lambda *a, **k: _Client(_Sftp(calls))
    )

    resolved = pds.resolve_plex_dbs(cfg, refresh=True)
    assert resolved.source == "ssh"
    assert resolved.library_db.name == pds.PLEX_LIBRARY_DB_NAME
    assert resolved.blobs_db.name == pds.PLEX_BLOBS_DB_NAME
    assert resolved.library_db.exists() and resolved.blobs_db.exists()
    # library + blobs, each with -wal and -shm sidecars
    assert len(calls) == 6

    # Cache hit: refresh=False reuses without re-fetching.
    assert pds.resolve_plex_dbs(cfg, refresh=False) == resolved
    assert len(calls) == 6


def test_ssh_source_missing_cache_without_refresh_raises(monkeypatch, tmp_path):
    cfg = _config(tmp_path, db_ssh_target="user@nas.local:/volume1/Plex")
    monkeypatch.setattr(pds, "_cache_dir", lambda target: tmp_path / "empty")
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg, refresh=False)


def test_ssh_fetch_error_maps_to_notfound(monkeypatch, tmp_path):
    cfg = _config(tmp_path, db_ssh_target="user@nas.local:/volume1/Plex")
    monkeypatch.setattr(pds, "_cache_dir", lambda target: tmp_path / "cache")
    monkeypatch.setattr(
        pds, "_open_ssh",
        lambda *a, **k: _Client(_Sftp([], fail_library=True)),
    )
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg, refresh=True)


def test_ssh_target_override_wins(monkeypatch, tmp_path):
    cfg = _config(tmp_path)  # no configured db_ssh_target
    cache = tmp_path / "cache"
    monkeypatch.setattr(pds, "_cache_dir", lambda target: cache)
    monkeypatch.setattr(
        pds, "_open_ssh", lambda *a, **k: _Client(_Sftp([]))
    )

    resolved = pds.resolve_plex_dbs(cfg, refresh=True, ssh_target="nas:/volume1/Plex")
    assert resolved.source == "ssh"
    assert resolved.library_db.parent == cache


def test_ssh_file_exists_ok(monkeypatch):
    class _StatSftp:
        def stat(self, path):
            return object()

        def close(self):
            pass

    class _StatClient:
        def open_sftp(self):
            return _StatSftp()

        def close(self):
            pass

    monkeypatch.setattr(pds, "_open_ssh", lambda *a, **k: _StatClient())
    assert pds.ssh_file_exists("u@h:/d", "file.db") is True


def test_ssh_file_exists_missing(monkeypatch):
    class _StatSftp:
        def stat(self, path):
            raise FileNotFoundError(path)

        def close(self):
            pass

    class _StatClient:
        def open_sftp(self):
            return _StatSftp()

        def close(self):
            pass

    monkeypatch.setattr(pds, "_open_ssh", lambda *a, **k: _StatClient())
    assert pds.ssh_file_exists("u@h:/d", "file.db") is False


def test_ssh_file_exists_unreachable(monkeypatch):
    def fail(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(pds, "_open_ssh", fail)
    assert pds.ssh_file_exists("u@h:/d", "file.db") is None
