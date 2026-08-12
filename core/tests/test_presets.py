"""Recommendation presets: one authoritative definition, no drift."""

from musicseed.recommender.scoring import RECOMMENDATION_PRESETS, Weights

EXPECTED_KEYS = {"sonic", "popularity", "style", "genre", "era", "novelty"}


def test_balanced_preset_equals_default_weights():
    assert RECOMMENDATION_PRESETS["balanced"] == Weights()


def test_all_presets_have_six_dimensions():
    for weights in RECOMMENDATION_PRESETS.values():
        assert set(weights.model_dump().keys()) == EXPECTED_KEYS


def test_presets_sum_positive():
    for weights in RECOMMENDATION_PRESETS.values():
        assert sum(weights.model_dump().values()) > 0
