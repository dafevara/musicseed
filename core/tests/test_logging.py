"""Tests for default log directory resolution."""

import logging
import stat

import musicseed.config as config_module
from musicseed.config import Config, set_config
from musicseed.logging_config import SecretRedactionFilter, resolve_log_level, setup_logging


def test_log_files_are_owner_only(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir)
    assert stat.S_IMODE((log_dir / "latest.log").stat().st_mode) == 0o600
    stamped = next(log_dir.glob("musicseed_*.log"))
    assert stat.S_IMODE(stamped.stat().st_mode) == 0o600


def test_secret_redaction_filter_scrubs_configured_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config_module._config = None
    config_module._config_path = None
    cfg = Config()
    cfg.plex.token = "SECRET-TOKEN"
    cfg.spotify.client_secret = "SECRET-SPOTIFY"
    set_config(cfg)

    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "musicseed.test", logging.ERROR, __file__, 1,
        "auth failed for token SECRET-TOKEN", None, None,
    )
    assert f.filter(record) is True
    assert record.getMessage() == "auth failed for token [REDACTED]"


def test_setup_logging_writes_to_explicit_dir(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir)
    assert (log_dir / "latest.log").is_file()
    stamped = list(log_dir.glob("musicseed_*.log"))
    assert len(stamped) == 1


def test_setup_logging_defaults_to_xdg_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    setup_logging()
    log_dir = tmp_path / "xdg" / "musicseed" / "logs"
    assert (log_dir / "latest.log").is_file()


def test_setup_logging_appends_to_latest(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir)
    first = (log_dir / "latest.log").read_text()
    setup_logging(log_dir=log_dir)
    second = (log_dir / "latest.log").read_text()
    assert first
    assert second.startswith(first)
    assert second.count("Logging initialized") == 2


def test_resolve_log_level_env_wins(monkeypatch) -> None:
    monkeypatch.setenv("MUSICSEED_LOG_LEVEL", "DEBUG")
    assert resolve_log_level(explicit="WARNING") == logging.DEBUG


def test_resolve_log_level_uses_explicit_without_env(monkeypatch) -> None:
    monkeypatch.delenv("MUSICSEED_LOG_LEVEL", raising=False)
    assert resolve_log_level(explicit="ERROR") == logging.ERROR
