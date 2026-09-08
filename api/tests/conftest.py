"""Shared fixtures: isolate config and DB engine per test."""

import musicseed.config as config_module
import musicseed_api.handlers.discovery as discovery_handlers
import pytest
from musicseed.clients.plex import ConnectionCheck
from musicseed.config import Config, set_config
from musicseed.db.session import reset_engine
from musicseed.services import discovery as core_discovery


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    # Even tests loading an empty config must never probe the owner's database.
    monkeypatch.setenv("HOME", str(tmp_path))
    config_module._config = None
    config_module._config_path = None
    set_config(Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}}))
    reset_engine()
    # Never read real Plex tokens or probe a NAS/server when exercising setup routes.
    monkeypatch.setattr(discovery_handlers, "read_plex_token", lambda: None)
    monkeypatch.setattr(core_discovery, "read_plex_token", lambda: None)
    monkeypatch.setattr(core_discovery, "ssh_file_exists", lambda *_a, **_kw: (False, None))

    class OfflinePlexProbe:
        def __init__(self, *_args, **_kwargs):
            pass

        def check_connection(self):
            return ConnectionCheck(
                reachable=False, authorized=False, status_code=None,
                server_version=None, error="offline test fixture",
            )

    monkeypatch.setattr(core_discovery, "PlexClient", OfflinePlexProbe)
    yield
    config_module._config = None
    config_module._config_path = None
    reset_engine()
