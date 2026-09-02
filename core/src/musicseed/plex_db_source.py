"""Resolve where MusicSeed's two Plex databases come from.

MusicSeed reads two SQLite files from the Plex host: the library database
(metadata) and the blobs database (sonic vectors). Both are normally local,
but for a remote Plex server MusicSeed fetches them itself over scp (using
the user's existing ``~/.ssh`` setup) into a local cache, then reads them
from there. The recommendation runtime never touches the remote files.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from musicseed.config import Config
from musicseed.exceptions import NotFoundError
from musicseed.logging_config import get_logger

logger = get_logger("plex_db_source")

SQLITE_HEADER = b"SQLite format 3\x00"
PLEX_LIBRARY_DB_NAME = "com.plexapp.plugins.library.db"
PLEX_BLOBS_DB_NAME = "com.plexapp.plugins.library.blobs.db"


@dataclass(frozen=True)
class ResolvedPlexDbs:
    """Local paths to the two Plex databases, plus where they came from."""

    library_db: Path
    blobs_db: Path
    source: str  # "local" | "ssh"


def parse_ssh_target(target: str) -> tuple[str, str]:
    """Split a scp-style ``[user@]host:/remote/dir`` into ``(host, remote_dir)``.

    Raises:
        NotFoundError: if the target has no ``host:/path`` shape.
    """
    host, sep, remote_dir = target.partition(":")
    if not sep or not host or not remote_dir.strip("/"):
        raise NotFoundError(
            f"Invalid SSH target '{target}'; expected [user@]host:/remote/directory"
        )
    return host, remote_dir.rstrip("/")


def _cache_dir(target: str) -> Path:
    """Cache directory for one SSH target (content-addressed by the target)."""
    digest = hashlib.sha256(target.encode()).hexdigest()[:16]
    xdg = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg) if xdg else Path.home() / ".cache"
    return root / "musicseed" / "plex-dbs" / digest


def _scp(host: str, remote_dir: str, filename: str, dest_dir: Path, *, required: bool) -> bool:
    """Copy one file from the remote host; return True when it was fetched.

    Optional files (WAL/SHM sidecars, or the blobs DB when absent) are skipped
    quietly. The main ``.db`` files are validated against the SQLite header.
    """
    dest = dest_dir / filename
    result = subprocess.run(
        ["scp", "-q", f"{host}:{remote_dir}/{filename}", str(dest)],
        capture_output=True,
    )
    if result.returncode != 0:
        if not required:
            return False
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()
        raise NotFoundError(
            f"Could not fetch {host}:{remote_dir}/{filename} over scp: "
            f"{detail or 'scp failed'}"
        )
    if filename.endswith(".db") and dest.read_bytes()[: len(SQLITE_HEADER)] != SQLITE_HEADER:
        raise NotFoundError(f"{filename} fetched from {host} is not a SQLite database.")
    return True


def _fetch_via_scp(target: str, dest_dir: Path) -> None:
    """Download the library + blobs databases (and their WAL sidecars) via scp."""
    host, remote_dir = parse_ssh_target(target)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for filename in (PLEX_LIBRARY_DB_NAME, PLEX_BLOBS_DB_NAME):
        _scp(host, remote_dir, filename, dest_dir, required=(filename == PLEX_LIBRARY_DB_NAME))
        for sidecar in ("-wal", "-shm"):
            _scp(host, remote_dir, f"{filename}{sidecar}", dest_dir, required=False)


def resolve_plex_dbs(
    config: Config, *, refresh: bool = False, ssh_target: str | None = None
) -> ResolvedPlexDbs:
    """Return local paths to the Plex library and blobs databases.

    With no ``db_ssh_target`` configured (or overridden), returns the
    configured local paths. Otherwise fetches the files over scp into a local
    cache, re-downloading when ``refresh`` is True (import time). When
    ``refresh`` is False and no snapshot is cached yet, raises
    ``NotFoundError`` rather than fetching.

    Args:
        config: resolved MusicSeed config.
        refresh: force a re-fetch of the remote files.
        ssh_target: per-call override for the scp target; falls back to
            ``config.plex.db_ssh_target``.

    Returns:
        The resolved local paths and the source label (``"local"`` or
        ``"ssh"``).

    Raises:
        NotFoundError: if the remote files cannot be fetched or (when not
            refreshing) have not been cached yet.
    """
    target = ssh_target or config.plex.db_ssh_target
    if not target:
        return ResolvedPlexDbs(
            library_db=config.plex.db_path_expanded,
            blobs_db=config.plex.blobs_db_path_expanded,
            source="local",
        )

    target_dir = _cache_dir(target)
    library_db = target_dir / PLEX_LIBRARY_DB_NAME
    blobs_db = target_dir / PLEX_BLOBS_DB_NAME

    if refresh:
        _fetch_via_scp(target, target_dir)
    elif not library_db.exists():
        raise NotFoundError(
            f"Plex database not cached yet; run an import to fetch it from {target}"
        )

    return ResolvedPlexDbs(library_db=library_db, blobs_db=blobs_db, source="ssh")
