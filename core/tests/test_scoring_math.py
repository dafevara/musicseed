"""Independent numerical checks complement the retrieval oracle's shared scorer."""

import math

import numpy as np
import pytest
from musicseed.db.models import Genre, Style, Track, TrackStats
from musicseed.recommender.scoring import (
    SeedProfile,
    Weights,
    calculate_score,
    cosine_similarity,
    era_proximity,
    jaccard,
    novelty_score,
    popularity_proximity,
    prepared_sonic_evidence,
    sonic_comparable,
)
from musicseed.sonic import SonicVectors, prepare_vector


@pytest.mark.parametrize(
    "function,args,expected",
    [
        (cosine_similarity, ([1, 0], [1, 0]), 1),
        (cosine_similarity, ([1, 0], [-1, 0]), 0),
        (cosine_similarity, ([1, 0], [0, 1]), 0.5),
        (cosine_similarity, (None, [1, 0]), 0.5),
        (cosine_similarity, ([0, 0], [1, 0]), 0.5),
        (jaccard, (set(), set()), 0.5),
        (jaccard, ({"rock"}, set()), 0),
        (jaccard, ({"rock"}, {"ambient"}), 0),
        (jaccard, ({"rock", "art"}, {"rock"}), 0.5),
        (popularity_proximity, (None, 50), 0.5),
        (popularity_proximity, (50, 50), 1),
        (popularity_proximity, (0, 100), 0),
        (popularity_proximity, (25, 75), 0.5),
        (era_proximity, (None, 2000), 0.5),
        (era_proximity, (2000, 2000), 1),
        (era_proximity, (2000, 2025), 0.5),
        (era_proximity, (1950, 2020), 0),
        (novelty_score, (None,), 1),
        (novelty_score, (0,), 1),
        (novelty_score, (5,), 0.5),
        (novelty_score, (20,), 0.2),
    ],
)
def test_numeric_primitives(function, args, expected):
    assert function(*args) == pytest.approx(expected)


def test_weight_normalization_matches_independent_weighted_formula():
    track = Track(
        plex_id=1,
        title="Fixture",
        year=2025,
        spotify_popularity=75,
        styles=[Style(name="rock")],
        genres=[Genre(name="ambient")],
        stats=TrackStats(play_count=5),
    )
    profile = SeedProfile(
        track_ids={2},
        embedding=np.array([1, 0]),
        styles={"rock", "alternative"},
        genres={"rock"},
        year=2000,
        popularity=50,
    )
    vectors = SonicVectors([1], np.array([[1, 1]], dtype=np.float32))
    weights = Weights()
    result = calculate_score(track, profile, weights, vectors)
    expected = (
        0.3 * ((1 + 1 / math.sqrt(2)) / 2) + 0.15 * 0.75 + 0.1 * 0.5 + 0.05 * 0.5 + 0.1 * 0.5
    ) / 0.85
    assert result.total == pytest.approx(expected)
    scaled = Weights(**{name: value * 10 for name, value in weights.model_dump().items()})
    assert calculate_score(track, profile, scaled, vectors).total == pytest.approx(expected)
    zero = Weights(**dict.fromkeys(weights.model_dump(), 0))
    assert calculate_score(track, profile, zero, vectors).total == 0


@pytest.mark.parametrize(
    "left,right",
    [
        ([1, 0], [1, 0]), ([1, 0], [-1, 0]), ([1, 0], [0, 1]),
        (None, [1, 0]), ([0, 0], [1, 0]), ([float("nan"), 1], [1, 0]),
        ([float("inf"), 1], [1, 0]), ([1e308, 1], [1, 0]),
        ([1e-300, 0], [1, 0]), ([1, 0], [1]), ([], [1]),
        ([[1, 0]], [1, 0]), (["invalid"], [1]),
    ],
)
def test_prepared_cosine_preserves_score_and_missing_evidence(left, right):
    assert prepared_sonic_evidence(prepare_vector(left), prepare_vector(right)) == (
        cosine_similarity(left, right), sonic_comparable(left, right),
    )


def test_prepared_cosine_preserves_float32_scalar_precision():
    rng = np.random.default_rng(13)
    for _ in range(100):
        left, right = rng.normal(size=(2, 50)).astype(np.float32)
        assert prepared_sonic_evidence(prepare_vector(left), prepare_vector(right)) == (
            cosine_similarity(left, right), True,
        )


def test_vector_snapshot_reuses_preparation_including_invalid_vectors(monkeypatch):
    vectors = SonicVectors([1, 2], np.array([[1, 2], [0, 0]], dtype=np.float32))
    original = np.linalg.norm
    calls = []

    def norm(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(np.linalg, "norm", norm)
    first = vectors.get_prepared(1)
    for _ in range(10):
        assert vectors.get_prepared(1) is first
        assert vectors.get_prepared(2) is None
        assert vectors.get_prepared(99) is None
    assert len(calls) == 2
