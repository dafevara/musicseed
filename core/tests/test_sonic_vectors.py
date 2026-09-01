"""The sonic-vector import persists Plex vectors locally (MUS-83)."""

import numpy as np
from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.db.models import TrackVector
from musicseed.db.session import init_db
from musicseed.services import sonic_vectors as svc
from musicseed.sonic import SonicVectors


def _context_for(tmp_path) -> MusicSeedContext:
    return MusicSeedContext(
        Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    )


def _fake_vectors() -> SonicVectors:
    matrix = np.asarray([[0.01] * 50, [0.02] * 50], dtype=np.float32)
    return SonicVectors([1, 2], matrix)


def test_import_plex_sonic_persists_vectors(monkeypatch, tmp_path):
    ctx = _context_for(tmp_path)
    init_db(ctx)
    monkeypatch.setattr(svc, "load_sonic_vectors", lambda **kwargs: _fake_vectors())

    result = svc.import_plex_sonic(context=ctx)
    assert result.total == 2
    assert result.imported == 2
    assert result.updated == 0

    with ctx.session() as session:
        rows = session.query(TrackVector).order_by(TrackVector.plex_id).all()
    assert [row.plex_id for row in rows] == [1, 2]
    assert all(len(row.vector) == 50 for row in rows)

    # Idempotent: re-running refreshes in place instead of inserting.
    again = svc.import_plex_sonic(context=ctx)
    assert again.imported == 0
    assert again.updated == 2
    with ctx.session() as session:
        assert session.query(TrackVector).count() == 2
