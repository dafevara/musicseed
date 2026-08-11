"""Smoke tests for the MusicSeed web scaffold."""

from conftest import make_dashboard, make_discovery
from fastapi.testclient import TestClient
from musicseed_web.app import create_app
from musicseed_web.routes import home

client = TestClient(create_app())


def test_index_serves_server_rendered_page(monkeypatch) -> None:
    monkeypatch.setattr(home, "discover", lambda **kw: make_discovery())
    monkeypatch.setattr(home, "get_dashboard_snapshot", lambda: make_dashboard())
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "MusicSeed" in response.text
    assert "htmx" in response.text


def test_healthz_returns_ok() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "musicseed-web"}


def test_clock_fragment_returns_html_partial() -> None:
    response = client.get("/fragments/clock")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "server-clock" in response.text
    # The fragment is a partial, not a full page.
    assert "<html" not in response.text


def test_static_assets_are_served() -> None:
    for path in ("/static/css/app.css", "/static/js/htmx.min.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert len(response.content) > 0
