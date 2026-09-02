"""Resolve where MusicSeed's two Plex databases come from.

MusicSeed reads two SQLite files from the Plex host: the library database
(metadata) and the blobs database (sonic vectors). Both are normally local,
but for a remote Plex server the same files can be served as a consistent
snapshot over HTTP. This module turns the configured source into local
``Path``s the readers can open, fetching a snapshot to a local cache when
needed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

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
    source: str  # "local" | "http"


def _cache_dir(url: str) -> Path:
    """Cache directory for one snapshot URL (content-addressed by the URL)."""
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    xdg = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg) if xdg else Path.home() / ".cache"
    return root / "musicseed" / "plex-dbs" / digest


def _fetch(url: str, dest: Path) -> None:
    """Download one snapshot file, verifying it is SQLite.

    Raises:
        NotFoundError: on any transport error or a non-SQLite response.
    """
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise NotFoundError(
            f"Could not fetch Plex database snapshot from {url}: {e}"
        ) from e
    if resp.content[: len(SQLITE_HEADER)] != SQLITE_HEADER:
        raise NotFoundError(f"Downloaded {url} is not a SQLite database.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)


def resolve_plex_dbs(config: Config, *, refresh: bool = False) -> ResolvedPlexDbs:
    """Return local paths to the Plex library and blobs databases.

    With no ``db_http_url`` configured, returns the configured local paths.
    With one, returns a locally cached snapshot, re-downloading both files
    when ``refresh`` is True (import time). When ``refresh`` is False and no
    snapshot is cached yet, raises ``NotFoundError`` rather than fetching.

    Args:
        config: resolved MusicSeed config.
        refresh: force a re-download of the remote snapshot.

    Returns:
        The resolved local paths and the source label (``"local"`` or
        ``"http"``).

    Raises:
        NotFoundError: if the HTTP snapshot cannot be fetched or (when not
            refreshing) has not been cached yet.
    """
    if not config.plex.db_http_url:
        return ResolvedPlexDbs(
            library_db=config.plex.db_path_expanded,
            blobs_db=config.plex.blobs_db_path_expanded,
            source="local",
        )

    base = config.plex.db_http_url.rstrip("/")
    target_dir = _cache_dir(base)
    library_db = target_dir / PLEX_LIBRARY_DB_NAME
    blobs_db = target_dir / PLEX_BLOBS_DB_NAME

    if refresh:
        _fetch(f"{base}/{PLEX_LIBRARY_DB_NAME}", library_db)
        _fetch(f"{base}/{PLEX_BLOBS_DB_NAME}", blobs_db)
    elif not (library_db.exists() and blobs_db.exists()):
        raise NotFoundError(
            f"Plex database snapshot not cached yet; run an import to fetch it "
            f"from {base}"
        )

    return ResolvedPlexDbs(library_db=library_db, blobs_db=blobs_db, source="http")
