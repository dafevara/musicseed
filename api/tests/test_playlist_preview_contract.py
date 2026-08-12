"""Playlist mutation contract: previews are read-only GET, mutations are POST."""

from fastapi.testclient import TestClient
from musicseed_api.app import create_app


def test_preview_is_get_and_mutations_are_post():
    client = TestClient(create_app())
    paths = client.app.openapi()["paths"]

    assert set(paths["/playlists/{name}/preview"].keys()) == {"get"}
    assert "post" in paths["/playlists/create"]
    assert "post" in paths["/playlists/{name}/populate"]
    assert "get" not in paths["/playlists/create"]
    assert "get" not in paths["/playlists/{name}/populate"]


def test_sonic_refresh_is_post_only():
    client = TestClient(create_app())
    paths = client.app.openapi()["paths"]

    assert "post" in paths["/sonic/refresh"]
    assert "get" not in paths["/sonic/refresh"]
