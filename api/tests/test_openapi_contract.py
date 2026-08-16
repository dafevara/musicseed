"""The API contract is auto-generated from the routes — assert every operation exists."""

from fastapi.testclient import TestClient
from musicseed_api.app import create_app

EXPECTED_OPERATIONS = {
    ("get", "/dashboard"),
    ("get", "/discovery"),
    ("post", "/discovery/check"),
    ("post", "/discovery/config"),
    ("post", "/discovery/init-db"),
    ("get", "/discovery/plex-servers"),
    ("post", "/enrichment/listenbrainz"),
    ("post", "/enrichment/spotify"),
    ("delete", "/jobs/{job_id}"),
    ("get", "/jobs/{job_id}"),
    ("post", "/jobs/{job_id}/cancel"),
    ("post", "/library/import"),
    ("get", "/library/status"),
    ("get", "/playlists"),
    ("post", "/playlists/create"),
    ("get", "/playlists/{playlist_id}/preview"),
    ("post", "/playlists/{playlist_id}/populate"),
    ("post", "/recommend"),
    ("get", "/recommend/presets"),
    ("get", "/recommend/typeahead"),
    ("get", "/sonic/status"),
    ("post", "/sonic/refresh"),
}


def test_every_operation_is_exposed():
    spec = TestClient(create_app()).app.openapi()
    actual = {
        (method, path)
        for path, methods in spec["paths"].items()
        for method in methods
    }
    assert EXPECTED_OPERATIONS <= actual


def test_get_discovery_does_not_accept_plex_token():
    spec = TestClient(create_app()).app.openapi()
    params = spec["paths"]["/discovery"]["get"].get("parameters", [])
    names = {p["name"] for p in params}
    assert "plex_token" not in names
