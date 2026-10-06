"""Logging configuration for MusicSeed."""

import logging
import os
from datetime import datetime
from pathlib import Path

from musicseed.config import default_log_dir

LOG_LEVEL_ENV = "MUSICSEED_LOG_LEVEL"


def _restrict_log_file(path: Path) -> None:
    """Create or tighten a log file to owner-only (0600) before it is written."""
    try:
        if path.exists():
            path.chmod(0o600)
        else:
            path.touch(mode=0o600)
    except OSError:  # pragma: no cover - non-POSIX filesystems
        pass


def _configured_secrets() -> set[str]:
    """Return the non-empty secret values that must never reach a log line."""
    from musicseed.config import get_config

    try:
        cfg = get_config()
    except Exception:  # pragma: no cover - redaction must never break logging
        return set()
    secrets = {
        cfg.plex.token,
        cfg.plex.db_ssh_password,
        cfg.spotify.client_id,
        cfg.spotify.client_secret,
        cfg.listenbrainz.token,
    }
    return {s for s in secrets if s}


class SecretRedactionFilter(logging.Filter):
    """Replace configured secret values with ``[REDACTED]`` in log messages.

    Attached to the ``musicseed`` logger so any ``musicseed.*`` record that
    accidentally carries a token, provider secret, or SSH password is scrubbed
    before it reaches a handler.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        original = record.getMessage()
        message = original
        for secret in _configured_secrets():
            message = message.replace(secret, "[REDACTED]")
        if message != original:
            record.msg = message
            record.args = ()
        return True


def parse_log_level(level: str | int) -> int:
    """Parse a logging level name or numeric value."""
    if isinstance(level, int):
        return level

    normalized = level.upper().strip()
    if normalized.isdigit():
        return int(normalized)

    parsed = getattr(logging, normalized, None)
    if not isinstance(parsed, int):
        valid = "DEBUG, INFO, WARNING, ERROR, CRITICAL"
        raise ValueError(f"Invalid log level '{level}'. Valid levels: {valid}")
    return parsed


def resolve_log_level(explicit: str | int | None = None, default: str = "INFO") -> int:
    """Env ``MUSICSEED_LOG_LEVEL`` wins, then ``explicit``, then ``default``."""
    env = os.environ.get(LOG_LEVEL_ENV)
    if env:
        return parse_log_level(env)
    if explicit is not None:
        return parse_log_level(explicit)
    return parse_log_level(default)


def setup_logging(
    level: int | str = logging.INFO,
    console: bool = False,
    console_level: int | str = logging.WARNING,
    log_dir: Path | None = None,
) -> logging.Logger:
    """Configure logging to files, with optional console logging.

    Args:
        level: File logging level (default: INFO)
        console: Whether to also emit logs to stderr
        console_level: Console logging level when console logging is enabled
        log_dir: Directory for log files. If None, uses
            ``~/.local/share/musicseed/logs`` (or ``$XDG_DATA_HOME/musicseed/logs``).

    Returns:
        The root logger configured for musicseed
    """
    if log_dir is None:
        log_dir = default_log_dir()

    log_dir.mkdir(parents=True, exist_ok=True)

    # Create timestamped log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"musicseed_{timestamp}.log"

    # Also keep a "latest" symlink/file for convenience
    latest_log = log_dir / "latest.log"

    # Logs may contain library paths and (rarely) secrets; keep them owner-only
    # from creation rather than tightening them after the first write.
    _restrict_log_file(log_file)
    _restrict_log_file(latest_log)

    resolved_level = parse_log_level(level)

    # Configure root logger for musicseed
    logger = logging.getLogger("musicseed")
    logger.setLevel(resolved_level)
    logger.propagate = False

    # Clear any existing handlers
    logger.handlers.clear()

    # Never let a configured secret reach a log line, whatever the handler.
    logger.addFilter(SecretRedactionFilter())

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(parse_log_level(console_level))
        console_format = logging.Formatter("%(levelname)s: %(message)s")
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

    # File handler - selected level and above, detailed format
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(resolved_level)
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    latest_handler = logging.FileHandler(latest_log, mode="a", encoding="utf-8")
    latest_handler.setLevel(resolved_level)
    latest_handler.setFormatter(file_format)
    logger.addHandler(latest_handler)

    # Log startup info
    logger.info(
        f"Logging initialized at {logging.getLevelName(resolved_level)}. "
        f"Log file: {log_file}"
    )

    return logger


def get_logger(name: str = "musicseed") -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name (will be prefixed with 'musicseed.' if not already)

    Returns:
        Logger instance
    """
    if not name.startswith("musicseed"):
        name = f"musicseed.{name}"
    return logging.getLogger(name)
