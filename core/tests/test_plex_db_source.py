"""Tests for musicseed.plex_db_source — local passthrough + HTTP snapshot fetch."""

import httpx
import musicseed.plex_db_source as pds
import pytest
from musicseed.config import Config
from musicseed.exceptions import NotFoundError


def _config(tmp_path, db_http_url: str = "") -> Config:
    return Config.model_validate({
        "database": {"path": str(tmp_path / "ms" / "musicseed.db")},
        "plex": {
            "db_path": str(tmp_path / "plex" / "com.plexapp.plugins.library.db"),
            "db_http_url": db_http_url,
        },
    })


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=None)


def test_local_source_returns_configured_paths(tmp_path):
    cfg = _config(tmp_path)
    resolved = pds.resolve_plex_dbs(cfg)
    assert resolved.source == "local"
    assert resolved.library_db == cfg.plex.db_path_expanded
    assert resolved.blobs_db == cfg.plex.blobs_db_path_expanded


def test_http_source_downloads_and_caches(monkeypatch, tmp_path):
    cfg = _config(tmp_path, db_http_url="http://nas.local:9000/plex-dbs")
    cache = tmp_path / "cache"
    monkeypatch.setattr(pds, "_cache_dir", lambda url: cache)

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(pds.SQLITE_HEADER + b"rest")

    monkeypatch.setattr(pds.httpx, "get", fake_get)

    resolved = pds.resolve_plex_dbs(cfg, refresh=True)
    assert resolved.source == "http"
    assert resolved.library_db.name == pds.PLEX_LIBRARY_DB_NAME
    assert resolved.blobs_db.name == pds.PLEX_BLOBS_DB_NAME
    assert resolved.library_db.exists() and resolved.blobs_db.exists()
    assert len(calls) == 2

    # Cache hit: refresh=False reuses without re-downloading.
    assert pds.resolve_plex_dbs(cfg, refresh=False) == resolved
    assert len(calls) == 2


def test_http_source_missing_cache_without_refresh_raises(monkeypatch, tmp_path):
    cfg = _config(tmp_path, db_http_url="http://nas.local:9000/plex-dbs")
    monkeypatch.setattr(pds, "_cache_dir", lambda url: tmp_path / "empty-cache")
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg, refresh=False)


def test_http_url_override_wins(monkeypatch, tmp_path):
    cfg = _config(tmp_path)  # no configured db_http_url
    cache = tmp_path / "cache"
    monkeypatch.setattr(pds, "_cache_dir", lambda url: cache)
    monkeypatch.setattr(
        pds.httpx, "get",
        lambda url, **kwargs: _FakeResponse(pds.SQLITE_HEADER + b"x"),
    )

    resolved = pds.resolve_plex_dbs(
        cfg, refresh=True, http_url="http://nas.local:9000/plex-dbs"
    )
    assert resolved.source == "http"
    assert resolved.library_db.parent == cache


def test_http_fetch_error_maps_to_notfound(monkeypatch, tmp_path):
    cfg = _config(tmp_path, db_http_url="http://nas.local:9000/plex-dbs")
    monkeypatch.setattr(pds, "_cache_dir", lambda url: tmp_path / "cache")

    def fake_get(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(pds.httpx, "get", fake_get)

    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg, refresh=True)
