"""Shared fixtures: isolate config and DB engine per test."""

import musicseed.config as config_module
import musicseed_api.handlers.discovery as discovery_handlers
import pytest
from musicseed.config import Config, set_config
from musicseed.db.session import reset_engine


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    config_module._config = None
    config_module._config_path = None
    set_config(Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}}))
    reset_engine()
    # Never read the real Plex installation's token in tests.
    monkeypatch.setattr(discovery_handlers, "read_plex_token", lambda: None)
    yield
    config_module._config = None
    config_module._config_path = None
    reset_engine()
