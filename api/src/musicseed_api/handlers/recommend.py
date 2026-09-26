"""Recommendation orchestration — seed parsing, typeahead, and recommendations."""

from __future__ import annotations

from musicseed.recommender.playlist import RecommendMethod
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
    method: RecommendMethod = "average",
    per_seed_limit: int = 30,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    weights: Weights | None = None,
) -> RecommendationResult:
    """Run the recommendation story line for a set of seed track ids.

    Delegates to core's ``get_recommendations`` unchanged. This handler exists
    to (a) validate that at least one seed is present before a confusing
    ValueError reaches the caller, and (b) give the CLI and web surfaces a
    framework-free callable that doesn't reach into core directly.

    Args:
        seed_ids: local seed track ids.
        limit: maximum number of recommendations to return.
        method: ``"average"`` or ``"frequency"``.
        per_seed_limit: candidates gathered per seed ("frequency" only).
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap during selection.
        min_score: drop recommendations below this total score.
        weights: signal weights; defaults to the "balanced" preset.

    Returns:
        The core ``RecommendationResult`` (resolved seeds, scored
        recommendations, and sonic coverage).

    Raises:
        ValueError: if ``seed_ids`` is empty.
    """
    if not seed_ids:
        raise ValueError("At least one seed track is required.")
    return get_recommendations(
        seed_ids=seed_ids,
        limit=limit,
        method=method,
        per_seed_limit=per_seed_limit,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
        weights=weights,
    )
