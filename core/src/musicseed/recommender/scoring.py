"""Scoring primitives for MusicSeed recommendations."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np
from pydantic import BaseModel

from musicseed.db.models import Track
from musicseed.sonic import SonicVectors


class Weights(BaseModel):
    """Normalized recommendation weights.

    Popularity means proximity to the seed popularity, not an absolute boost.
    Artist diversity is enforced as a selection constraint, not as a score component.
    Weights are normalized by their sum at scoring time, so absolute values only
    control relative importance.
    """

    model_config = {"frozen": True}

    sonic: float = 0.30
    popularity: float = 0.15
    style: float = 0.10
    genre: float = 0.15
    era: float = 0.05
    novelty: float = 0.10


# The single authoritative set of named recommendation presets. "balanced" is
# exactly the default ``Weights()`` — every surface (CLI, API, web) must use
# these rather than duplicating values. The web UI fetches this from the API.
RECOMMENDATION_PRESETS: dict[str, Weights] = {
    "balanced": Weights(),
    "sonic": Weights(
        sonic=0.55, popularity=0.10, style=0.10, genre=0.10, era=0.05, novelty=0.10
    ),
    "discovery": Weights(
        sonic=0.15, popularity=0.05, style=0.10, genre=0.10, era=0.05, novelty=0.55
    ),
    "popular": Weights(
        sonic=0.15, popularity=0.45, style=0.10, genre=0.15, era=0.05, novelty=0.10
    ),
}


class SeedProfile(BaseModel):
    """Aggregated recommendation signals from one or more seed tracks."""

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    track_ids: set[int]
    embedding: Any  # np.ndarray | None
    styles: set[str]
    genres: set[str]
    year: int | None
    popularity: float | None


class ScoreBreakdown(BaseModel):
    """Component-level score details for explainable CLI output."""

    model_config = {"frozen": True}

    total: float
    sonic: float
    popularity: float
    style: float
    genre: float
    era: float
    novelty: float


class SonicCoverage(BaseModel):
    """How many scored candidates actually had a Plex sonic vector.

    A candidate without a vector scores a neutral ``0.5`` on the sonic
    dimension, indistinguishable from a genuine mid-similarity match. Surfacing
    this count lets a caller tell a flattened dimension from real coverage.
    """

    model_config = {"frozen": True}

    candidates: int
    with_vector: int


def _as_vector(value: object) -> np.ndarray | None:
    if value is None:
        return None
    vector = np.asarray(value, dtype=float)
    if vector.size == 0:
        return None
    return vector


def cosine_similarity(
    a: Sequence[float] | np.ndarray | None,
    b: Sequence[float] | np.ndarray | None,
) -> float:
    """Return cosine similarity normalized from [-1, 1] into [0, 1].

    Args:
        a: first vector; None or empty means "unknown".
        b: second vector; None or empty means "unknown".

    Returns:
        The normalized similarity, or the neutral ``0.5`` when either vector
        is missing or has zero norm.
    """
    left = _as_vector(a)
    right = _as_vector(b)
    if left is None or right is None:
        return 0.5

    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0:
        return 0.5

    raw = float(np.dot(left, right) / denom)
    return max(0.0, min(1.0, (raw + 1.0) / 2.0))


def jaccard(left: set[str], right: set[str]) -> float:
    """Return the Jaccard similarity of two tag sets.

    Args:
        left: first tag set (e.g. seed styles).
        right: second tag set (e.g. candidate styles).

    Returns:
        ``|left ∩ right| / |left ∪ right|``. Returns the neutral ``0.5``
        when both sets are empty (no information either way) and ``0.0``
        when exactly one side is empty (known mismatch).
    """
    if not left and not right:
        return 0.5
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def average_or_none(values: Iterable[float | int | None]) -> float | None:
    """Return the mean of the non-None values, or None when there are none.

    Args:
        values: numbers, any of which may be None.

    Returns:
        The arithmetic mean over the concrete values, or None when every
        value is None.
    """
    concrete = [float(value) for value in values if value is not None]
    if not concrete:
        return None
    return sum(concrete) / len(concrete)


def track_popularity_value(track: Track) -> float | None:
    """Return the best available popularity value on a 0-100 scale."""
    if track.popularity_score is not None:
        return max(0.0, min(100.0, track.popularity_score * 100))
    if track.spotify_popularity is not None:
        return float(track.spotify_popularity)
    return None


def build_seed_profile(seed_tracks: Sequence[Track], vectors: SonicVectors) -> SeedProfile:
    """Aggregate one or more seed tracks into a single recommendation profile.

    The sonic embedding is the element-wise mean of the seed vectors (None
    when no seed has a vector); styles and genres are the union across seeds;
    year and popularity are averaged over the seeds that have them.

    Args:
        seed_tracks: the resolved seed tracks.
        vectors: the query-time Plex sonic vector store.

    Returns:
        The aggregated seed profile used for candidate generation and
        scoring.
    """
    embeddings = [
        vector
        for vector in (vectors.get(track.plex_id) for track in seed_tracks)
        if vector is not None
    ]
    embedding = np.mean(embeddings, axis=0) if embeddings else None

    styles = {style.name for track in seed_tracks for style in track.styles}
    genres = {genre.name for track in seed_tracks for genre in track.genres}
    year = average_or_none(track.year for track in seed_tracks)
    popularity = average_or_none(track_popularity_value(track) for track in seed_tracks)

    return SeedProfile(
        track_ids={track.id for track in seed_tracks},
        embedding=embedding,
        styles=styles,
        genres=genres,
        year=round(year) if year is not None else None,
        popularity=popularity,
    )


def popularity_proximity(
    seed_popularity: float | None, candidate_popularity: float | None
) -> float:
    """Score how close a candidate's popularity is to the seed's.

    Popularity is a *proximity* signal, not an absolute boost: a candidate at
    the seed's popularity scores 1.0, and the score decays linearly to 0.0 at
    100 popularity points of distance (the full 0-100 scale).

    Args:
        seed_popularity: seed popularity on a 0-100 scale, or None.
        candidate_popularity: candidate popularity on a 0-100 scale, or None.

    Returns:
        Proximity in [0, 1], or the neutral ``0.5`` when either side is
        unknown.
    """
    if seed_popularity is None or candidate_popularity is None:
        return 0.5
    return max(0.0, min(1.0, 1.0 - abs(seed_popularity - candidate_popularity) / 100.0))


def era_proximity(seed_year: int | None, candidate_year: int | None) -> float:
    """Score how close a candidate's release year is to the seed's.

    Same-year releases score 1.0; the score decays linearly to 0.0 at 50
    years of distance.

    Args:
        seed_year: seed release year, or None.
        candidate_year: candidate release year, or None.

    Returns:
        Proximity in [0, 1], or the neutral ``0.5`` when either side is
        unknown.
    """
    if seed_year is None or candidate_year is None:
        return 0.5
    return max(0.0, min(1.0, 1.0 - abs(seed_year - candidate_year) / 50.0))


def novelty_score(play_count: int | None) -> float:
    """Score a candidate's novelty from its local play count.

    Never-played tracks score 1.0; the score decays as ``1 / (1 + 0.2 *
    plays)``, so 5 plays yields ~0.5 and 20 plays ~0.2.

    Args:
        play_count: local play count; None is treated as 0.

    Returns:
        Novelty in (0, 1].
    """
    count = play_count or 0
    return 1.0 / (1.0 + count * 0.2)


def calculate_score(
    candidate: Track,
    seed: SeedProfile,
    weights: Weights,
    vectors: SonicVectors,
) -> ScoreBreakdown:
    """Score one candidate against a seed profile on all six signals.

    Each signal produces a component in [0, 1]; signals with missing data
    (no sonic vector, unknown popularity/year, empty tag sets on both sides)
    contribute the neutral ``0.5`` rather than zero, so missing data neither
    rewards nor punishes a candidate. The total is the weighted mean of the
    components — weights are normalized by their sum, so absolute weight
    values only control relative importance.

    Args:
        candidate: the track to score.
        seed: the aggregated seed profile.
        weights: per-signal weights.
        vectors: the query-time Plex sonic vector store.

    Returns:
        The total score plus every component score for explainability.
    """
    candidate_styles = {style.name for style in candidate.styles}
    candidate_genres = {genre.name for genre in candidate.genres}
    play_count = candidate.stats.play_count if candidate.stats else 0

    # cosine_similarity returns the 0.5 neutral when either side has no vector.
    sonic = cosine_similarity(vectors.get(candidate.plex_id), seed.embedding)
    popularity = popularity_proximity(seed.popularity, track_popularity_value(candidate))
    style = jaccard(seed.styles, candidate_styles) if seed.styles else 0.5
    genre = jaccard(seed.genres, candidate_genres) if seed.genres else 0.5
    era = era_proximity(seed.year, candidate.year)
    novelty = novelty_score(play_count)

    total_weight = (
        weights.sonic
        + weights.popularity
        + weights.style
        + weights.genre
        + weights.era
        + weights.novelty
    )
    if total_weight <= 0:
        total_weight = 1.0

    total = (
        sonic * weights.sonic
        + popularity * weights.popularity
        + style * weights.style
        + genre * weights.genre
        + era * weights.era
        + novelty * weights.novelty
    ) / total_weight

    return ScoreBreakdown(
        total=total,
        sonic=sonic,
        popularity=popularity,
        style=style,
        genre=genre,
        era=era,
        novelty=novelty,
    )
