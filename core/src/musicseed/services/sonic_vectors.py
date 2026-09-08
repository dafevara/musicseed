"""Sonic vector persistence — import Plex vectors into the local database.

MusicSeed reads Plex sonic-analysis vectors from Plex's blobs database and
persists them into the local ``track_vectors`` table so recommendations no
longer depend on that file at query time. The blobs database is only read by
``import_plex_sonic``; scoring reads the local store via the context.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from musicseed.context import MusicSeedContext, get_context
from musicseed.db.models import RuntimeState, TrackVector
from musicseed.db.session import ensure_schema
from musicseed.plex_db_source import resolve_plex_dbs
from musicseed.services.jobs import exclusive_writer
from musicseed.sonic import load_sonic_vectors


class SonicVectorImportResult(BaseModel):
    """Counts from one sonic-vector import run."""

    total: int
    imported: int
    updated: int


@exclusive_writer("sonic_import")
def import_plex_sonic(
    context: MusicSeedContext | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    *,
    batch_size: int = 500,
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
        progress_callback: optional callback after each committed batch.
        should_cancel: polled before source reads and between committed batches.
            Source backup/decoding must finish before cancellation is checked again.
        batch_size: maximum vector upserts per committed transaction.

    Returns:
        The total number of vectors found in Plex and how many rows were newly
        inserted versus updated in place.

    Raises:
        NotFoundError: if the Plex blobs database is unavailable.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    ctx = context or get_context()
    if should_cancel is not None and should_cancel():
        return SonicVectorImportResult(total=0, imported=0, updated=0)
    if progress_callback is not None:
        progress_callback(0, 0, "reading Plex snapshot")
    dbs = resolve_plex_dbs(ctx.config, refresh=True)
    vectors = load_sonic_vectors(
        plex_db_path=dbs.library_db,
        blobs_db_path=dbs.blobs_db,
        library_name=ctx.config.plex.library,
    )

    total = len(vectors)
    imported = 0
    updated = 0
    processed = 0

    ensure_schema(ctx)
    plex_ids = sorted(vectors.plex_ids)
    for start in range(0, total, batch_size):
        if should_cancel is not None and should_cancel():
            break
        ids = plex_ids[start:start + batch_size]
        with ctx.session() as session:
            existing = set(session.scalars(select(TrackVector.plex_id).where(
                TrackVector.plex_id.in_(ids)
            )))
            statement = insert(TrackVector).values([
                {"plex_id": pid, "vector": vectors.get(pid).tolist()} for pid in ids
            ])
            session.execute(statement.on_conflict_do_update(
                index_elements=[TrackVector.plex_id],
                set_={"vector": statement.excluded.vector, "updated_at": func.now()},
            ))
            revision = insert(RuntimeState).values(key="sonic_generation", value=1)
            session.execute(revision.on_conflict_do_update(
                index_elements=[RuntimeState.key], set_={"value": RuntimeState.value + 1},
            ))
        # Only count/report durable rows, with no competing writer transaction open.
        imported += len(ids) - len(existing)
        updated += len(existing)
        processed += len(ids)
        if progress_callback is not None:
            progress_callback(processed, total, "sonic vectors")

    ctx.reset_sonic_vectors()

    return SonicVectorImportResult(total=total, imported=imported, updated=updated)
