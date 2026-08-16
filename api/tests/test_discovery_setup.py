"""Setup-flow tests: config persistence of validated Plex overrides + empty DB."""

import musicseed.config as config_module
from fastapi.testclient import TestClient
from musicseed.config import load_config, set_config
from musicseed_api.app import create_app
from musicseed_api.handlers.discovery import apply_config_and_init_db


def _seed_config(tmp_path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"database:\n  path: {tmp_path / 'original.db'}\n")
    set_config(load_config(cfg_path))


def test_apply_config_persists_plex_overrides_and_creates_fresh_db(tmp_path):
    _seed_config(tmp_path)
    db_path = tmp_path / "musicseed.db"

    apply_config_and_init_db(
        musicseed_db_path=str(db_path),
        spotify_client_id="cid",
        spotify_client_secret="secret",
        listenbrainz_token="lb-tok",
        plex_url="http://plex.local:32400",
        plex_token="token123",
        plex_library="Music2",
        plex_db_path=str(tmp_path / "plex.db"),
    )

    config_module._config = None
    config_module._config_path = None
    reloaded = load_config(tmp_path / "config.yaml")
    assert reloaded.database.path == str(db_path)
    assert reloaded.spotify.client_id == "cid"
    assert reloaded.spotify.client_secret == "secret"
    assert reloaded.listenbrainz.token == "lb-tok"
    assert reloaded.plex.url == "http://plex.local:32400"
    assert reloaded.plex.token == "token123"
    assert reloaded.plex.library == "Music2"
    assert reloaded.plex.db_path == str(tmp_path / "plex.db")
    assert db_path.exists()


def test_init_db_route_forwards_plex_overrides(tmp_path):
    _seed_config(tmp_path)
    client = TestClient(create_app())
    db_path = tmp_path / "route.db"

    resp = client.post(
        "/discovery/init-db",
        data={
            "musicseed_db_path": str(db_path),
            "spotify_client_id": "cid",
            "spotify_client_secret": "secret",
            "listenbrainz_token": "lb-secret-token",
            "plex_url": "http://plex.local:32400",
            "plex_token": "secrettoken123",
            "plex_library": "Music2",
            "plex_db_path": str(tmp_path / "plex.db"),
        },
    )

    assert resp.status_code == 200
    assert "secrettoken123" not in resp.text  # secret never echoed
    assert "lb-secret-token" not in resp.text  # secret never echoed

    config_module._config = None
    config_module._config_path = None
    reloaded = load_config(tmp_path / "config.yaml")
    assert reloaded.plex.url == "http://plex.local:32400"
    assert reloaded.plex.token == "secrettoken123"
    assert reloaded.listenbrainz.token == "lb-secret-token"
    assert reloaded.database.path == str(db_path)
    assert db_path.exists()
