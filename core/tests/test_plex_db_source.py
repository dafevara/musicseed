"""Tests for musicseed.plex_db_source — local passthrough + SSH scp fetch."""

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


class _FakeProc:
    returncode = 0
    stderr = b""
    stdout = b""


def _fake_scp(argv, **kwargs) -> _FakeProc:
    dest = Path(argv[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(pds.SQLITE_HEADER + b"rest")
    return _FakeProc()


def test_parse_ssh_target():
    assert pds.parse_ssh_target("user@nas.local:/volume1/Plex") == (
        "user@nas.local",
        "/volume1/Plex",
    )
    assert pds.parse_ssh_target("nas:/a/b/") == ("nas", "/a/b")
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

    calls = []
    monkeypatch.setattr(
        pds.subprocess, "run",
        lambda argv, **kwargs: calls.append(argv) or _fake_scp(argv, **kwargs),
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

    class _FailProc:
        returncode = 1
        stderr = b"connection refused"
        stdout = b""

    monkeypatch.setattr(
        pds.subprocess, "run",
        lambda argv, **kwargs: _FailProc(),
    )
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg, refresh=True)


def test_ssh_target_override_wins(monkeypatch, tmp_path):
    cfg = _config(tmp_path)  # no configured db_ssh_target
    cache = tmp_path / "cache"
    monkeypatch.setattr(pds, "_cache_dir", lambda target: cache)
    monkeypatch.setattr(
        pds.subprocess, "run",
        lambda argv, **kwargs: _fake_scp(argv, **kwargs),
    )

    resolved = pds.resolve_plex_dbs(
        cfg, refresh=True, ssh_target="nas:/volume1/Plex"
    )
    assert resolved.source == "ssh"
    assert resolved.library_db.parent == cache
