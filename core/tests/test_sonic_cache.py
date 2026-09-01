"""The context's sonic-vector cache loads from the local database (MUS-83)."""

import musicseed.sonic as sonic
from musicseed.config import Config
from musicseed.context import MusicSeedContext, reset_context, set_context
from musicseed.db.models import TrackVector
from musicseed.db.session import init_db


def _context_for(tmp_path) -> MusicSeedContext:
    return MusicSeedContext(
        Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    )


def _vector(n: int = 50) -> list[float]:
    return [float(i) / n for i in range(n)]


def test_sonic_vectors_loaded_from_local_table(tmp_path):
    ctx = _context_for(tmp_path)
    init_db(ctx)
    with ctx.session() as session:
        session.add(TrackVector(plex_id=1, vector=_vector()))
        session.add(TrackVector(plex_id=2, vector=_vector()))

    vectors = ctx.sonic_vectors
    assert len(vectors) == 2
    assert 1 in vectors and 2 in vectors
    assert vectors.get(1) is not None

    # Cached: a second access returns the same object.
    assert ctx.sonic_vectors is vectors


def test_reset_sonic_vectors_reloads_from_table(tmp_path):
    ctx = _context_for(tmp_path)
    init_db(ctx)
    with ctx.session() as session:
        session.add(TrackVector(plex_id=1, vector=_vector()))

    assert len(ctx.sonic_vectors) == 1

    with ctx.session() as session:
        session.add(TrackVector(plex_id=2, vector=_vector()))

    # Stale until the cache is reset.
    assert len(ctx.sonic_vectors) == 1
    ctx.reset_sonic_vectors()
    assert len(ctx.sonic_vectors) == 2


def test_get_sonic_vectors_delegates_to_default_context(tmp_path):
    ctx = _context_for(tmp_path)
    init_db(ctx)
    set_context(ctx)
    try:
        assert sonic.get_sonic_vectors() is ctx.sonic_vectors
    finally:
        reset_context()
