"""Tests for default log directory resolution."""

from musicseed.logging_config import setup_logging


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
