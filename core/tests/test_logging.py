"""Tests for default log directory resolution."""

import logging

from musicseed.logging_config import resolve_log_level, setup_logging


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
