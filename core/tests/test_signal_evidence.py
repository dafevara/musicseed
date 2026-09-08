"""Availability is truthful without changing established finite-input score policy."""

import numpy as np
import pytest
from musicseed.db.models import Track
from musicseed.recommender.populate import _average_score
from musicseed.recommender.scoring import (
    SIGNALS,
    ScoreBreakdown,
    SeedProfile,
    Weights,
    calculate_score,
    cosine_similarity,
)
from musicseed.sonic import SonicVectors


def seed(**overrides):
    return SeedProfile(track_ids={1}, embedding=overrides.get("embedding", np.ones(50)),
                       styles={"rock"}, genres={"rock"}, year=2000, popularity=50)


def test_absent_candidate_tags_keep_zero_policy_but_are_not_observed_mismatches():
    candidate = Track(title="Missing tags", plex_id=2, year=2000, spotify_popularity=50)
    score = calculate_score(candidate, seed(), Weights(), SonicVectors([2], np.ones((1, 50))))
    assert score.style == score.genre == 0
    assert score.availability["style"] == score.availability["genre"] == "missing"
    assert score.total == pytest.approx(0.6 / 0.85)


@pytest.mark.parametrize("embedding", [None, np.zeros(50), np.full(50, np.nan), np.ones(49)])
def test_unusable_seed_vector_is_neutral_not_observed(embedding):
    candidate = Track(title="Candidate", plex_id=2)
    score = calculate_score(candidate, seed(embedding=embedding), Weights(),
                            SonicVectors([2], np.ones((1, 50))))
    assert score.sonic == 0.5
    assert score.availability["sonic"] == "neutral_missing"


def test_zero_candidate_vector_is_neutral_not_observed():
    score = calculate_score(Track(title="Zero vector", plex_id=2), seed(), Weights(),
                            SonicVectors([2], np.zeros((1, 50))))
    assert score.sonic == 0.5
    assert score.availability["sonic"] == "neutral_missing"


@pytest.mark.parametrize("vector", [[float("inf")], [float("nan")], [[1, 2]], ["invalid"]])
def test_invalid_vectors_do_not_become_perfect_similarity_or_crash(vector):
    assert cosine_similarity(vector, [1, 2]) == 0.5


def test_average_scores_preserves_numbers_and_marks_mixed_or_unknown_evidence():
    observed = ScoreBreakdown(total=0.2, **dict.fromkeys(SIGNALS, 0.2),
                              availability=dict.fromkeys(SIGNALS, "observed"))
    missing = ScoreBreakdown(total=0.8, **dict.fromkeys(SIGNALS, 0.8),
                             availability={**observed.availability, "sonic": "neutral_missing"})
    averaged = _average_score([observed, missing])
    assert averaged.total == pytest.approx(0.5)
    for signal in SIGNALS:
        assert getattr(averaged, signal) == pytest.approx(0.5)
    assert averaged.availability["sonic"] == "mixed"
    assert all(averaged.availability[k] == "observed" for k in SIGNALS if k != "sonic")
    assert _average_score([observed, observed]).availability == observed.availability
    legacy = observed.model_copy(update={"availability": {}})
    assert _average_score([legacy]).availability == dict.fromkeys(SIGNALS, "unknown")
    assert _average_score([legacy, observed]).availability == dict.fromkeys(SIGNALS, "mixed")
