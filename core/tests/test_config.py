"""Tests for config persistence — save_config/load_config round-trips."""

import stat

import musicseed.config as config_module
from musicseed.config import (
    Config,
    default_log_dir,
    default_plex_data_dir,
    load_config,
    plex_data_dir_candidates,
    plex_library_db_candidates,
    reload_config,
    save_config,
    set_config,
    url_is_remote_cleartext,
)


def _reset_globals() -> None:
    config_module._config = None
    config_module._config_path = None


def test_url_is_remote_cleartext() -> None:
    # Local and home-LAN HTTP stay supported.
    assert not url_is_remote_cleartext("http://localhost:32400")
    assert not url_is_remote_cleartext("http://127.0.0.1:32400")
    assert not url_is_remote_cleartext("http://192.168.1.5:32400")
    assert not url_is_remote_cleartext("http://nas.lan:32400")
    assert not url_is_remote_cleartext("http://plex.local:32400")
    # https:// to any host keeps certificate verification; not cleartext.
    assert not url_is_remote_cleartext("https://plex.example.com")
    # Plain http:// to a remote host is cleartext.
    assert url_is_remote_cleartext("http://plex.example.com")
    assert url_is_remote_cleartext("http://8.8.8.8:32400")


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


def test_save_config_is_owner_only(tmp_path) -> None:
    """The config file holds credentials, so it must not be group/world readable."""
    path = tmp_path / "config.yaml"
    save_config(Config(), path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    # An existing file with loose permissions is tightened, not left alone.
    path.chmod(0o644)
    save_config(Config(), path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_config_is_atomic_without_temp_leftovers(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    save_config(Config(), path)
    # Atomic replace writes a same-directory temp then moves it into place.
    assert list(tmp_path.glob("*.tmp")) == []
    assert path.is_file()


def test_reload_config_rereads_the_same_file(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    first = Config()
    first.plex.token = "first"
    save_config(first, path)
    set_config(first)  # this process cached the pre-link config

    # Another surface (the Plex sign-in flow) rewrites the file on disk.
    second = Config()
    second.plex.token = "second"
    save_config(second, path)

    assert config_module.get_config().plex.token == "first"
    assert reload_config().plex.token == "second"
    assert config_module.get_config().plex.token == "second"
    _reset_globals()


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
