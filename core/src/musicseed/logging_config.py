"""Logging configuration for MusicSeed."""

import logging
from datetime import datetime
from pathlib import Path


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
        log_dir: Directory for log files. If None, uses project root/logs

    Returns:
        The root logger configured for musicseed
    """
    # Find project root (where pyproject.toml is)
    if log_dir is None:
        # Try to find logs dir relative to this file
        current = Path(__file__).parent
        while current != current.parent:
            if (current / "pyproject.toml").exists():
                log_dir = current / "logs"
                break
            current = current.parent
        else:
            # Fallback to current directory
            log_dir = Path.cwd() / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)

    # Create timestamped log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"musicseed_{timestamp}.log"

    # Also keep a "latest" symlink/file for convenience
    latest_log = log_dir / "latest.log"

    resolved_level = parse_log_level(level)

    # Configure root logger for musicseed
    logger = logging.getLogger("musicseed")
    logger.setLevel(resolved_level)
    logger.propagate = False

    # Clear any existing handlers
    logger.handlers.clear()

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

    # Also write to latest.log (overwrite each run)
    latest_handler = logging.FileHandler(latest_log, mode="w", encoding="utf-8")
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
