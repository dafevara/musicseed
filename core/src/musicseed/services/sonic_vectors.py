"""Sonic vector persistence — import Plex vectors into the local database.

MusicSeed reads Plex sonic-analysis vectors from Plex's blobs database and
persists them into the local ``track_vectors`` table so recommendations no
longer depend on that file at query time. The blobs database is only read by
``import_plex_sonic``; scoring reads the local store via the context.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from musicseed.context import MusicSeedContext, get_context
from musicseed.db.models import TrackVector
from musicseed.db.session import ensure_schema
from musicseed.sonic import load_sonic_vectors


class SonicVectorImportResult(BaseModel):
    """Counts from one sonic-vector import run."""

    total: int
    imported: int
    updated: int


def import_plex_sonic(
    context: MusicSeedContext | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> SonicVectorImportResult:
    """Import Plex sonic-analysis vectors into the local database.

    Reads the Plex blobs database once (via ``sonic.load_sonic_vectors``) and
    upserts every vector into ``track_vectors`` keyed by ``plex_id``. The
    operation is idempotent: existing rows are refreshed in place and new rows
    are inserted, so re-running after Plex analyzes more tracks is safe. After
    writing, the context's cached vectors are dropped so the next scoring run
    reads the fresh store.

    Args:
        context: runtime context to use; defaults to the default context.
        progress_callback: optional ``(current, total, phase)`` callback
            invoked once when the import finishes.
        should_cancel: optional callable polled between vectors; the import
            stops early when it returns True.

    Returns:
        The total number of vectors found in Plex and how many rows were newly
        inserted versus updated in place.

    Raises:
        NotFoundError: if the Plex blobs database is unavailable.
    """
    ctx = context or get_context()
    vectors = load_sonic_vectors(
        plex_db_path=ctx.config.plex.db_path_expanded,
        blobs_db_path=ctx.config.plex.blobs_db_path_expanded,
        library_name=ctx.config.plex.library,
    )

    total = len(vectors)
    imported = 0
    updated = 0
    processed = 0

    ensure_schema(ctx)
    with ctx.session() as session:
        for plex_id in sorted(vectors.plex_ids):
            if should_cancel is not None and should_cancel():
                break
            vector = vectors.get(plex_id)
            row = session.get(TrackVector, plex_id)
            if row is None:
                session.add(TrackVector(plex_id=plex_id, vector=vector.tolist()))
                imported += 1
            else:
                row.vector = vector.tolist()
                updated += 1
            processed += 1

    ctx.reset_sonic_vectors()
    if progress_callback is not None:
        progress_callback(processed, total, "sonic vectors")

    return SonicVectorImportResult(total=total, imported=imported, updated=updated)
