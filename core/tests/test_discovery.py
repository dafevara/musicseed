"""Tests for services.discovery — no real Plex installation or network involved."""

import json
import os
from pathlib import Path

import httpx
import pytest
from musicseed.clients import plex_api
from musicseed.clients.plex_api import (
    ConnectionCheck,
    LibrarySectionResult,
    PlexClient,
)
from musicseed.config import Config, PlexConfig
from musicseed.services import discovery
from musicseed.services.discovery import Reason, discover

SECRET_TOKEN = "SECRET-TOKEN-123"


def _make_sqlite(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    return path


@pytest.fixture
def isolated_plex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the hardcoded default Plex paths into a temp dir."""
    plex_dir = tmp_path / "Plex"

    class FakePlexConfig(PlexConfig):
        db_path: str = str(plex_dir / "com.plexapp.plugins.library.db")

    monkeypatch.setattr(discovery, "PlexConfig", FakePlexConfig)
    return plex_dir


def _config(tmp_path: Path, **plex_kwargs) -> Config:
    plex = {
        # keep tests away from the real Plex installation's default path
        "db_path": str(tmp_path / "plex" / "com.plexapp.plugins.library.db"),
        **plex_kwargs,
    }
    return Config.model_validate({
        "database": {"path": str(tmp_path / "ms" / "musicseed.db")},
        "plex": plex,
    })


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    check: ConnectionCheck,
    sections: list[LibrarySectionResult] | None = None,
) -> None:
    class FakeClient:
        def __init__(self, url: str, token: str, timeout: float = 15.0) -> None:
            pass

        def check_connection(self) -> ConnectionCheck:
            return check

        def list_library_sections(self) -> list[LibrarySectionResult]:
            return sections or []

    monkeypatch.setattr(discovery, "PlexClient", FakeClient)


def _ok_check() -> ConnectionCheck:
    return ConnectionCheck(
        reachable=True, authorized=True, status_code=200,
        server_version="1.41.0", error=None,
    )


def _music_section(title: str = "Music") -> LibrarySectionResult:
    return LibrarySectionResult(key="1", title=title, type="artist")


# ---------------------------------------------------------------- files


def test_musicseed_db_exists_and_writable(tmp_path: Path) -> None:
    db = _make_sqlite(tmp_path / "musicseed.db")
    result = discover(musicseed_db_path=str(db), check_server=False,
                      config=_config(tmp_path))
    assert result.musicseed_db.ok
    assert result.musicseed_db.exists
    assert result.musicseed_db.writable
    assert result.musicseed_db.reason is Reason.OK
    assert result.musicseed_db.source == "override"


def test_musicseed_db_creatable_when_parent_writable(tmp_path: Path) -> None:
    result = discover(musicseed_db_path=str(tmp_path / "sub" / "musicseed.db"),
                      check_server=False, config=_config(tmp_path))
    # parent "sub" does not exist yet → not creatable until init-db makes it
    assert result.musicseed_db.reason is Reason.PARENT_MISSING
    assert not result.musicseed_db.ok

    (tmp_path / "sub").mkdir()
    result = discover(musicseed_db_path=str(tmp_path / "sub" / "musicseed.db"),
                      check_server=False, config=_config(tmp_path))
    assert result.musicseed_db.creatable
    assert result.musicseed_db.ok
    assert not result.musicseed_db.exists


def test_musicseed_db_not_writable(tmp_path: Path) -> None:
    db = _make_sqlite(tmp_path / "musicseed.db")
    os.chmod(db, 0o444)
    result = discover(musicseed_db_path=str(db), check_server=False,
                      config=_config(tmp_path))
    assert result.musicseed_db.reason is Reason.NOT_WRITABLE
    assert not result.musicseed_db.ok


def test_plex_dbs_found_with_derived_blobs(tmp_path: Path, isolated_plex: Path) -> None:
    library_db = _make_sqlite(isolated_plex / "com.plexapp.plugins.library.db")
    _make_sqlite(isolated_plex / "com.plexapp.plugins.library.blobs.db")

    result = discover(plex_db_path=str(library_db), check_server=False,
                      config=_config(tmp_path))

    assert result.plex_library_db.ok
    assert result.plex_library_db.selected is not None
    assert result.plex_library_db.selected.path == str(library_db)
    assert result.plex_blobs_db.ok
    assert result.plex_blobs_db.selected is not None
    assert result.plex_blobs_db.selected.path.endswith(".blobs.db")


def test_plex_db_missing(tmp_path: Path, isolated_plex: Path) -> None:
    missing = isolated_plex / "com.plexapp.plugins.library.db"
    result = discover(check_server=False, config=_config(tmp_path))

    assert not result.plex_library_db.ok
    assert result.plex_library_db.selected is None
    assert all(c.reason is Reason.NOT_FOUND for c in result.plex_library_db.candidates)
    assert str(missing) in {c.path for c in result.plex_library_db.candidates}


def test_plex_db_not_readable(tmp_path: Path, isolated_plex: Path) -> None:
    library_db = _make_sqlite(isolated_plex / "com.plexapp.plugins.library.db")
    _make_sqlite(isolated_plex / "com.plexapp.plugins.library.blobs.db")
    os.chmod(library_db, 0o000)

    result = discover(check_server=False, config=_config(tmp_path))
    reasons = {c.reason for c in result.plex_library_db.candidates}
    assert Reason.NOT_READABLE in reasons
    assert not result.plex_library_db.ok


def test_plex_db_invalid_sqlite(tmp_path: Path, isolated_plex: Path) -> None:
    bad = isolated_plex / "com.plexapp.plugins.library.db"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("this is not a sqlite file")

    result = discover(check_server=False, config=_config(tmp_path))
    reasons = {c.reason for c in result.plex_library_db.candidates}
    assert Reason.INVALID_SQLITE in reasons
    assert not result.plex_library_db.ok


# ---------------------------------------------------------------- server


def test_server_ok_and_library_found(tmp_path: Path, isolated_plex: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    _make_sqlite(isolated_plex / "com.plexapp.plugins.library.db")
    _make_sqlite(isolated_plex / "com.plexapp.plugins.library.blobs.db")
    db = _make_sqlite(tmp_path / "ms" / "musicseed.db")
    _patch_client(monkeypatch, check=_ok_check(), sections=[_music_section()])

    result = discover(musicseed_db_path=str(db), config=_config(tmp_path))

    assert result.plex_server.ok
    assert result.plex_server.reason is Reason.OK
    assert result.plex_server.server_version == "1.41.0"
    assert result.plex_server.library_found
    assert result.ready


def test_server_unreachable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, check=ConnectionCheck(
        reachable=False, authorized=False, status_code=None,
        server_version=None, error="Cannot reach Plex at http://localhost:32400",
    ))
    result = discover(config=_config(tmp_path))
    assert result.plex_server.reason is Reason.UNREACHABLE
    assert not result.plex_server.ok
    assert not result.ready


def test_server_unauthorized_with_token(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, check=ConnectionCheck(
        reachable=True, authorized=False, status_code=401,
        server_version=None, error="Plex returned HTTP 401.",
    ))
    result = discover(plex_token=SECRET_TOKEN, config=_config(tmp_path))
    assert result.plex_server.reason is Reason.UNAUTHORIZED
    assert result.plex_server.token_configured


def test_server_missing_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, check=ConnectionCheck(
        reachable=True, authorized=False, status_code=401,
        server_version=None, error="Plex returned HTTP 401.",
    ))
    result = discover(config=_config(tmp_path))  # no token anywhere
    assert result.plex_server.reason is Reason.MISSING_TOKEN
    assert not result.plex_server.token_configured


def test_server_library_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, check=_ok_check(),
                  sections=[_music_section(title="Films")])
    result = discover(config=_config(tmp_path))
    assert result.plex_server.reason is Reason.LIBRARY_NOT_FOUND
    assert not result.plex_server.library_found
    assert "Music" in (result.plex_server.detail or "")


def test_server_check_skipped(tmp_path: Path) -> None:
    result = discover(check_server=False, config=_config(tmp_path))
    assert result.plex_server.reason is Reason.SKIPPED
    assert not result.ready  # ready requires every check to pass


# ---------------------------------------------------------------- safety


def test_overrides_do_not_mutate_config(tmp_path: Path, isolated_plex: Path) -> None:
    cfg = _config(tmp_path, url="http://plex.local:32400", token=SECRET_TOKEN)
    result = discover(
        plex_url="http://other:32400", plex_token="override-token",
        check_server=False, config=cfg,
    )
    assert result.plex_server.url == "http://other:32400"
    assert result.plex_server.source == "override"
    assert cfg.plex.url == "http://plex.local:32400"
    assert cfg.plex.token == SECRET_TOKEN


def test_token_never_appears_in_results(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, check=ConnectionCheck(
        reachable=True, authorized=False, status_code=401,
        server_version=None, error="Plex returned HTTP 401.",
    ))
    result = discover(plex_token=SECRET_TOKEN, config=_config(tmp_path))
    assert SECRET_TOKEN not in json.dumps(result.model_dump(), default=str)


# ---------------------------------------------------------------- client probe


def test_check_connection_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plex_api.httpx, "get",
        lambda *a, **k: httpx.Response(
            200, json={"MediaContainer": {"version": "1.41.0"}}
        ),
    )
    check = PlexClient("http://localhost:32400", "tok").check_connection()
    assert check.reachable and check.authorized
    assert check.server_version == "1.41.0"
    assert check.error is None


def test_check_connection_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plex_api.httpx, "get", lambda *a, **k: httpx.Response(401))
    check = PlexClient("http://localhost:32400", "bad-tok").check_connection()
    assert check.reachable
    assert not check.authorized
    assert check.status_code == 401


def test_check_connection_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(plex_api.httpx, "get", _raise)
    check = PlexClient("http://localhost:32400", SECRET_TOKEN).check_connection()
    assert not check.reachable
    assert not check.authorized
    assert check.error is not None
    assert SECRET_TOKEN not in check.error
