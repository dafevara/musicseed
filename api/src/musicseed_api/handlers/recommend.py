"""Recommendation orchestration — seed parsing, typeahead, and recommendations."""

from __future__ import annotations

from musicseed.db.models import Artist, Track
from musicseed.db.session import get_session
from musicseed.recommender.scoring import RECOMMENDATION_PRESETS, Weights
from musicseed.services.recommend import RecommendationResult, get_recommendations
from sqlalchemy.orm import joinedload


def get_recommendation_presets() -> dict[str, dict[str, float]]:
    """Return the authoritative named presets (see ``RECOMMENDATION_PRESETS``)."""
    return {name: weights.model_dump() for name, weights in RECOMMENDATION_PRESETS.items()}


def parse_seed_ids(raw: str) -> list[int]:
    """Parse a comma-separated seed-id string into a deduplicated int list."""
    return [int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]


def load_seed_tracks(ids: list[int]) -> list[Track]:
    """Load full Track objects for a list of seed ids, preserving input order."""
    if not ids:
        return []
    with get_session() as session:
        tracks = (
            session.query(Track)
            .options(joinedload(Track.artist))
            .filter(Track.id.in_(ids))
            .all()
        )
    track_map = {t.id: t for t in tracks}
    return [track_map[i] for i in ids if i in track_map]


def typeahead_search(query: str, exclude_ids: list[int] | None = None) -> list[Track]:
    """Search tracks by title or artist name for autocomplete.

    Returns at most 10 matches, excluding any ids in ``exclude_ids``.
    Returns an empty list when the query is shorter than 2 characters.
    """
    q = query.strip()
    if len(q) < 2:
        return []
    exclude = exclude_ids or []
    with get_session() as session:
        return (
            session.query(Track)
            .options(joinedload(Track.artist), joinedload(Track.album))
            .outerjoin(Artist, Track.artist_id == Artist.id)
            .filter(
                Track.title.ilike(f"%{q}%")
                | Artist.name.ilike(f"%{q}%")
            )
            .filter(~Track.id.in_(exclude) if exclude else True)
            .order_by(Track.title)
            .all()
        )


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
