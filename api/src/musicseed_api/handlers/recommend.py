"""Recommendation orchestration — seed parsing, typeahead, and recommendations."""

from __future__ import annotations

from musicseed.recommender.scoring import RECOMMENDATION_PRESETS, Weights
from musicseed.services.recommend import RecommendationResult, get_recommendations
from musicseed.services.typeahead import TypeaheadTrack, search_tracks


def get_recommendation_presets() -> dict[str, dict[str, float]]:
    """Return the authoritative named presets (see ``RECOMMENDATION_PRESETS``)."""
    return {name: weights.model_dump() for name, weights in RECOMMENDATION_PRESETS.items()}


def parse_seed_ids(raw: str) -> list[int]:
    """Parse a comma-separated seed-id string into a deduplicated int list."""
    return [int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]


def typeahead_search(query: str, exclude_ids: list[int] | None = None) -> list[TypeaheadTrack]:
    """Search tracks for autocomplete (delegates to the core typeahead service)."""
    return search_tracks(query, exclude_ids)


def run_recommendations(
    seed_ids: list[int],
    limit: int = 50,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    weights: Weights | None = None,
) -> RecommendationResult:
    """Run the full recommendation pipeline for a set of seed track ids."""
    if not seed_ids:
        raise ValueError("At least one seed track is required.")
    return get_recommendations(
        seed_ids=seed_ids,
        limit=limit,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
        weights=weights,
    )
