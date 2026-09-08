"""Scoring availability tests — distinguish real scores from neutral fallbacks (MUS-79)."""

import numpy as np
from musicseed.db.models import Genre, Style, Track
from musicseed.recommender.scoring import (
    ScoreBreakdown,
    SeedProfile,
    Weights,
    calculate_score,
)
from musicseed.sonic import SonicVectors


def _embedding(*values) -> np.ndarray:
    vec = np.zeros(50, dtype=np.float32)
    for i, v in enumerate(values):
        vec[i] = v
    return vec


def test_missing_data_marks_neutral_and_not_applicable():
    candidate = Track(title="candidate", plex_id=1, year=None, spotify_popularity=None)
    seed = SeedProfile(
        track_ids=set(),
        embedding=None,
        styles=set(),
        genres=set(),
        year=None,
        popularity=None,
    )
    vectors = SonicVectors([], np.zeros((0, 50), dtype=np.float32))

    score = calculate_score(candidate, seed, Weights(), vectors)

    assert score.availability == {
        "sonic": "neutral_missing",
        "popularity": "neutral_missing",
        "style": "not_applicable",
        "genre": "not_applicable",
        "era": "neutral_missing",
        "novelty": "observed",
    }
    # Missing-data signals stay at the neutral 0.5.
    assert score.sonic == 0.5
    assert score.popularity == 0.5
    assert score.style == 0.5
    assert score.genre == 0.5
    assert score.era == 0.5


def test_present_data_marks_all_signals_observed():
    candidate = Track(
        title="candidate", plex_id=1, year=2000, spotify_popularity=50,
        styles=[Style(name="rock")], genres=[Genre(name="rock")],
    )
    seed = SeedProfile(
        track_ids=set(),
        embedding=_embedding(1.0),
        styles={"rock"},
        genres={"rock"},
        year=2000,
        popularity=50.0,
    )
    matrix = np.zeros((1, 50), dtype=np.float32)
    matrix[0, 0] = 1.0
    vectors = SonicVectors([1], matrix)

    score = calculate_score(candidate, seed, Weights(), vectors)

    assert score.availability == {
        "sonic": "observed",
        "popularity": "observed",
        "style": "observed",
        "genre": "observed",
        "era": "observed",
        "novelty": "observed",
    }


def test_score_breakdown_availability_defaults_to_empty():
    breakdown = ScoreBreakdown(
        total=0.5, sonic=0.5, popularity=0.5, style=0.5, genre=0.5, era=0.5, novelty=0.5
    )
    assert breakdown.availability == {}
