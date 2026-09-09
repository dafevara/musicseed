"""Source-specific durable import checkpoints and read-only status queries."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from musicseed.context import MusicSeedContext
from musicseed.db.models import ImportState
from musicseed.exceptions import NotFoundError
from musicseed.plex_db_source import parse_ssh_target


def source_key(context: MusicSeedContext) -> str:
    """Identity excludes credentials and includes library, source and Plex server."""
    plex = context.config.plex
    source = (
        [*parse_ssh_target(plex.db_ssh_target), plex.db_ssh_port]
        if plex.db_ssh_target else [str(plex.db_path_expanded.resolve())]
    )
    return hashlib.sha256(json.dumps([plex.url, plex.library, source]).encode()).hexdigest()


def snapshot_id(path: Path) -> str:
    """Identify the observed input generation, including local file changes."""
    stat = path.stat()
    wal_path = Path(str(path) + "-wal")
    try:
        wal = wal_path.stat()
        wal_signature = [wal.st_ino, wal.st_size, wal.st_mtime_ns]
    except FileNotFoundError:
        wal_signature = None
    return json.dumps([
        str(path.resolve()), stat.st_ino, stat.st_size, stat.st_mtime_ns, wal_signature,
    ])


def read_import_state(context: MusicSeedContext) -> dict | None:
    """Read without initializing/migrating; unknown is not a successful import."""
    path = context.config.database.path_expanded
    if not path.exists():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM import_state WHERE source_key = ?", (source_key(context),)
            ).fetchone()
            return dict(row) if row else None
    except (sqlite3.Error, NotFoundError):
        return None


def checkpoint(
    context: MusicSeedContext,
    state: str,
    *,
    snapshot: str | None = None,
    expected: dict | None = None,
    phase: str | None = None,
    processed: int | None = None,
) -> None:
    """Write a checkpoint outside the importer's write transaction."""
    from musicseed.services.jobs import current_job_id

    key = source_key(context)
    with context.session() as session:
        row = session.get(ImportState, key)
        if row is None:
            row = ImportState(source_key=key, state=state)
            session.add(row)
        row.state = state
        row.job_id = current_job_id()
        if snapshot is not None:
            row.snapshot = snapshot
        if expected is not None:
            row.expected = expected
        if phase is not None:
            row.checkpoint = phase
        if processed is not None:
            row.processed = processed
        if state == "complete":
            row.completed_at = datetime.now(UTC).replace(tzinfo=None)
