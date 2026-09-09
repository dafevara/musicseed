"""Regression tests for candidate-pool generation."""

import numpy as np
from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.db.models import Track
from musicseed.db.session import init_db
from musicseed.recommender.candidates import build_candidate_pool
from musicseed.recommender.scoring import SeedProfile
from musicseed.sonic import SonicVectors


def _context(tmp_path) -> MusicSeedContext:
    return MusicSeedContext(
        Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    )


def _embedding(*values) -> np.ndarray:
    """A 50-dim embedding with ``values`` at the front and zeros elsewhere."""
    vec = np.zeros(50, dtype=np.float32)
    for i, v in enumerate(values):
        vec[i] = v
    return vec


def test_year_window_restricts_sonic_neighbors_before_ranking(tmp_path):
    """The sonic source must not be starved when the global nearest neighbors
    fall outside the requested era (MUS-78).

    Global-then-filter would rank 60 out-of-era tracks (cosine 1.0) ahead of
    the single in-era track (cosine ~0.707), then drop them all in SQL — leaving
    no sonic candidates. Restricting the search to the era first must surface
    the in-era track.
    """
    ctx = _context(tmp_path)
    init_db(ctx)

    with ctx.session() as session:
        in_window = Track(title="in-window", plex_id=1, year=2000)
        session.add(in_window)
        for i in range(60):
            session.add(Track(title=f"out-{i}", plex_id=100 + i, year=1980))
        session.flush()
        in_window_local_id = in_window.id
        assert in_window_local_id is not None

        plex_ids = [1] + [100 + i for i in range(60)]
        matrix = np.zeros((len(plex_ids), 50), dtype=np.float32)
        matrix[0, 0] = 1.0  # in-window: ~0.707 cosine with the seed
        matrix[0, 1] = 1.0
        matrix[1:, 0] = 1.0  # out-of-window: 1.0 cosine with the seed
        vectors = SonicVectors(plex_ids, matrix)

        seed = SeedProfile(
            track_ids=set(),
            embedding=_embedding(1.0),
            styles=set(),
            genres=set(),
            year=None,
            popularity=None,
        )

        pool = build_candidate_pool(
            session,
            seed,
            vectors,
            limit=10,
            year_min=1990,
            year_max=2010,
        )

    sonic_candidates = [
        track_id
        for track_id in pool.track_ids
        if "sonic" in pool.sources_for(track_id)
    ]
    assert sonic_candidates == [in_window_local_id]


def test_nearest_restricts_to_allowed_plex_ids():
    """nearest(..., allowed=...) ranks only the requested Plex ids."""
    plex_ids = [1, 2, 3]
    matrix = np.zeros((3, 50), dtype=np.float32)
    matrix[0, 0] = 1.0  # plex_id 1 -> cosine 1.0 with [1,0,...]
    matrix[1, 0] = 0.9  # plex_id 2 -> cosine 1.0 (normalized)
    matrix[2, 1] = 1.0  # plex_id 3 -> cosine 0.0 (orthogonal)
    vectors = SonicVectors(plex_ids, matrix)

    assert vectors.nearest(_embedding(1.0), 3, allowed={3}) == [3]
    assert vectors.nearest(_embedding(1.0), 3, allowed={1, 3}) == [1, 3]
    assert vectors.nearest(_embedding(1.0), 3, allowed=set()) == []
    assert vectors.nearest(_embedding(1.0), 3, allowed={999}) == []
    # Without a restriction, all stored ids are eligible.
    assert set(vectors.nearest(_embedding(1.0), 3)) == {1, 2, 3}
