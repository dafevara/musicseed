"""Setup-flow tests: config persistence of validated Plex overrides + empty DB."""

import musicseed.config as config_module
from fastapi.testclient import TestClient
from musicseed.config import load_config, set_config
from musicseed_api.app import create_app
from musicseed_api.handlers.discovery import apply_config_and_init_db


def _seed_config(tmp_path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        f"database:\n  path: {tmp_path / 'original.db'}\n"
        "security:\n  allowed_hosts:\n    - testserver\n"
    )
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
        plex_db_ssh="user@nas.local:/volume1/Plex/Databases",
        plex_db_ssh_password="hunter2",
        plex_db_ssh_port="2222",
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
    assert reloaded.plex.db_ssh_target == "user@nas.local:/volume1/Plex/Databases"
    assert reloaded.plex.db_ssh_password == "hunter2"
    assert reloaded.plex.db_ssh_port == 2222
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
            "plex_db_ssh": "user@nas.local:/volume1/Plex/Databases",
            "plex_db_ssh_password": "hunter2",
            "plex_db_ssh_port": "2222",
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
    assert reloaded.plex.db_ssh_target == "user@nas.local:/volume1/Plex/Databases"
    assert reloaded.plex.db_ssh_password == "hunter2"
    assert reloaded.plex.db_ssh_port == 2222
    assert reloaded.database.path == str(db_path)
    assert db_path.exists()


def test_selecting_a_server_keeps_the_token_but_changing_ssh_target_clears_password(tmp_path):
    from musicseed_api.handlers.discovery import save_config_overrides

    _seed_config(tmp_path)
    save_config_overrides(plex_url="http://old.local:32400", plex_token="tok1")
    save_config_overrides(
        plex_db_ssh="user@old.local:/volume1/Plex", plex_db_ssh_password="pw1"
    )

    # The Plex token is account-wide: selecting a different server keeps it (the
    # setup wizard saves the picked server URL without replaying the token).
    save_config_overrides(plex_url="http://new.local:32400")
    # An SSH password is target-specific: changing the target clears it.
    save_config_overrides(plex_db_ssh="user@new.local:/volume1/Plex")

    config_module._config = None
    config_module._config_path = None
    reloaded = load_config(tmp_path / "config.yaml")
    assert reloaded.plex.url == "http://new.local:32400"
    assert reloaded.plex.token == "tok1"
    assert reloaded.plex.db_ssh_target == "user@new.local:/volume1/Plex"
    assert reloaded.plex.db_ssh_password == ""


def test_wizard_selecting_a_server_keeps_the_plex_signin(tmp_path, monkeypatch):
    """Regression: picking a server after Plex sign-in must keep the token."""
    import musicseed_api.handlers.discovery as discovery_handlers
    from musicseed.clients.plex import ConnectionCheck, LibrarySectionResult
    from musicseed.services import discovery as core_discovery

    class FakeClient:
        def __init__(self, url, token, timeout=15.0):
            self._token = token

        def check_connection(self):
            return ConnectionCheck(
                reachable=True, authorized=bool(self._token),
                status_code=200 if self._token else 401,
                server_version="1.41.0", error=None,
            )

        def list_library_sections(self):
            return [LibrarySectionResult(key="1", title="Music", type="artist")]

    monkeypatch.setattr(core_discovery, "PlexClient", FakeClient)
    _seed_config(tmp_path)
    discovery_handlers.save_config_overrides(plex_token="tok1")

    # The wizard saves the picked server URL without replaying the token.
    discovery_handlers.save_config_overrides(plex_url="http://192.168.1.5:32400")

    result = core_discovery.discover()
    assert result.plex_server.token_source == "config"
    assert result.plex_server.ok, result.plex_server.detail
