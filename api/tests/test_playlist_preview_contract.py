"""Playlist mutation contract: previews are read-only GET, mutations are POST."""

from fastapi.testclient import TestClient
from musicseed_api.app import create_app


def test_preview_is_get_and_mutations_are_post():
    client = TestClient(create_app())
    paths = client.app.openapi()["paths"]

    assert set(paths["/playlists/{playlist_id}/preview"].keys()) == {"get"}
    assert "post" in paths["/playlists/create"]
    assert "post" in paths["/playlists/{playlist_id}/populate"]
    assert "get" not in paths["/playlists/create"]
    assert "get" not in paths["/playlists/{playlist_id}/populate"]


def test_sonic_refresh_is_post_only():
    client = TestClient(create_app())
    paths = client.app.openapi()["paths"]

    assert "post" in paths["/sonic/refresh"]
    assert "get" not in paths["/sonic/refresh"]


def test_trigger_sonic_refresh_resets_vector_cache(monkeypatch):
    import musicseed_api.handlers.sonic as sonic_handler

    called = []
    monkeypatch.setattr(sonic_handler, "refresh_sonic_analysis", lambda *a, **k: "ok")
    monkeypatch.setattr(sonic_handler, "reset_sonic_vectors", lambda: called.append(1))

    result = sonic_handler.trigger_sonic_refresh()

    assert result == "ok"
    assert called == [1]
