"""Serve wrapper: API at /api, optional static UI at /."""

from pathlib import Path

from fastapi.testclient import TestClient
from musicseed_api.app import create_app
from musicseed_api.server import create_ui_app, resolve_static_dir


def test_create_app_stays_unprefixed():
    resp = TestClient(create_app()).get("/discovery")
    assert resp.status_code == 200
    assert "first_run" in resp.json() or "result" in resp.json() or "ready" in resp.json()


def test_ui_app_mounts_api_at_prefix():
    client = TestClient(create_ui_app(static_dir=Path("/nonexistent")))
    bare = client.get("/discovery")
    assert bare.status_code == 404
    prefixed = client.get("/api/discovery")
    assert prefixed.status_code == 200


def test_ui_app_serves_index_when_static_present(tmp_path: Path):
    (tmp_path / "index.html").write_text("<html><body>ui</body></html>")
    (tmp_path / "setup").mkdir()
    (tmp_path / "setup" / "index.html").write_text("<html><body>setup</body></html>")
    client = TestClient(create_ui_app(static_dir=tmp_path))
    home = client.get("/")
    assert home.status_code == 200
    assert "ui" in home.text
    setup = client.get("/setup/")
    assert setup.status_code == 200
    assert "setup" in setup.text
    assert client.get("/api/discovery").status_code == 200


def test_ui_app_without_static_is_api_only():
    client = TestClient(create_ui_app(static_dir=Path("/definitely-missing")))
    assert client.get("/").status_code == 404
    assert client.get("/api/discovery").status_code == 200


def test_main_help_exits_zero(monkeypatch):
    import sys

    from musicseed_api.server import main

    monkeypatch.setattr(sys, "argv", ["musicseed", "--help"])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected --help to SystemExit")


def test_resolve_static_dir_honors_env(tmp_path: Path, monkeypatch):
    (tmp_path / "index.html").write_text("ok")
    monkeypatch.setenv("MUSICSEED_STATIC_DIR", str(tmp_path))
    assert resolve_static_dir() == tmp_path
    monkeypatch.setenv("MUSICSEED_STATIC_DIR", str(tmp_path / "missing"))
    assert resolve_static_dir() is None
