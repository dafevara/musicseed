"""Tests for config persistence — save_config/load_config round-trips."""

import musicseed.config as config_module
from musicseed.config import (
    Config,
    default_log_dir,
    default_plex_data_dir,
    load_config,
    plex_data_dir_candidates,
    plex_library_db_candidates,
    save_config,
)


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


def test_default_log_dir_uses_xdg_data_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert default_log_dir() == tmp_path / "xdg" / "musicseed" / "logs"


def test_plex_candidates_include_macos_and_linux() -> None:
    dirs = plex_data_dir_candidates()
    rendered = [str(path) for path in dirs]
    assert any(path.endswith("Library/Application Support/Plex Media Server") for path in rendered)
    assert any("/var/lib/plexmediaserver/" in path for path in rendered)
    assert any("/var/snap/plexmediaserver/" in path for path in rendered)
    assert any(".local/share/plexmediaserver/" in path for path in rendered)
    dbs = plex_library_db_candidates()
    assert len(dbs) == len(dirs)
    assert all(db.name == "com.plexapp.plugins.library.db" for db in dbs)


def test_default_plex_data_dir_prefers_existing(monkeypatch, tmp_path) -> None:
    existing = tmp_path / "linux-plex"
    existing.mkdir()
    missing = tmp_path / "missing-plex"
    monkeypatch.setattr(
        config_module,
        "plex_data_dir_candidates",
        lambda: [missing, existing],
    )
    assert default_plex_data_dir() == existing
