"""Tests for config persistence — save_config/load_config round-trips."""

import musicseed.config as config_module
from musicseed.config import Config, load_config, save_config


def _reset_globals() -> None:
    config_module._config = None
    config_module._config_path = None


def test_save_config_round_trips_values(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    cfg = Config()
    cfg.database.path = str(tmp_path / "musicseed.db")
    cfg.spotify.client_id = "cid"
    cfg.spotify.client_secret = "secret"

    save_config(cfg, path)

    _reset_globals()
    loaded = load_config(path)
    assert loaded.database.path == str(tmp_path / "musicseed.db")
    assert loaded.spotify.client_id == "cid"
    assert loaded.spotify.client_secret == "secret"


def test_save_config_remembers_path(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    cfg = Config()
    cfg.database.path = str(tmp_path / "db1.db")
    save_config(cfg, path)

    cfg.database.path = str(tmp_path / "db2.db")
    save_config(cfg)

    _reset_globals()
    assert load_config(path).database.path == str(tmp_path / "db2.db")


def test_save_config_falls_back_to_default(monkeypatch, tmp_path) -> None:
    _reset_globals()
    monkeypatch.setattr(config_module, "default_config_path", lambda: tmp_path / "config.yaml")

    cfg = Config()
    cfg.spotify.client_secret = "secret"
    save_config(cfg)

    _reset_globals()
    assert load_config(tmp_path / "config.yaml").spotify.client_secret == "secret"
