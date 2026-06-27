"""Scoring primitives for MusicSeed recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from musicseed.db.models import Track


@dataclass(frozen=True)
class Weights:
    """Normalized recommendation weights.

    Popularity means proximity to the seed popularity, not an absolute boost.
    Artist diversity is enforced as a selection constraint, not as a score component.
    """

    sonic: float = 0.30
    popularity: float = 0.15
    mood: float = 0.15
    style: float = 0.10
    genre: float = 0.15
    era: float = 0.05
    novelty: float = 0.10


@dataclass(frozen=True)
class SeedProfile:
    """Aggregated recommendation signals from one or more seed tracks."""

    track_ids: set[int]
    embedding: np.ndarray | None
    moods: set[str]
    styles: set[str]
    genres: set[str]
    year: int | None
    popularity: float | None


@dataclass(frozen=True)
class ScoreBreakdown:
    """Component-level score details for explainable CLI output."""

    total: float
    sonic: float
    popularity: float
    mood: float
    style: float
    genre: float
    era: float
    novelty: float


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
    """Return cosine similarity normalized from [-1, 1] into [0, 1]."""
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
    if not left and not right:
        return 0.5
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def average_or_none(values: Iterable[float | int | None]) -> float | None:
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


def build_seed_profile(seed_tracks: Sequence[Track]) -> SeedProfile:
    embeddings = [
        _as_vector(track.embedding) for track in seed_tracks if track.embedding is not None
    ]
    embedding = np.mean(embeddings, axis=0) if embeddings else None

    moods = {mood.name for track in seed_tracks for mood in track.moods}
    styles = {style.name for track in seed_tracks for style in track.styles}
    genres = {genre.name for track in seed_tracks for genre in track.genres}
    year = average_or_none(track.year for track in seed_tracks)
    popularity = average_or_none(track_popularity_value(track) for track in seed_tracks)

    return SeedProfile(
        track_ids={track.id for track in seed_tracks},
        embedding=embedding,
        moods=moods,
        styles=styles,
        genres=genres,
        year=round(year) if year is not None else None,
        popularity=popularity,
    )


def popularity_proximity(
    seed_popularity: float | None, candidate_popularity: float | None
) -> float:
    if seed_popularity is None or candidate_popularity is None:
        return 0.5
    return max(0.0, min(1.0, 1.0 - abs(seed_popularity - candidate_popularity) / 100.0))


def era_proximity(seed_year: int | None, candidate_year: int | None) -> float:
    if seed_year is None or candidate_year is None:
        return 0.5
    return max(0.0, min(1.0, 1.0 - abs(seed_year - candidate_year) / 50.0))


def novelty_score(play_count: int | None) -> float:
    count = play_count or 0
    return 1.0 / (1.0 + count * 0.2)


def calculate_score(candidate: Track, seed: SeedProfile, weights: Weights) -> ScoreBreakdown:
    candidate_moods = {mood.name for mood in candidate.moods}
    candidate_styles = {style.name for style in candidate.styles}
    candidate_genres = {genre.name for genre in candidate.genres}
    play_count = candidate.stats.play_count if candidate.stats else 0

    sonic = cosine_similarity(candidate.embedding, seed.embedding)
    popularity = popularity_proximity(seed.popularity, track_popularity_value(candidate))
    mood = jaccard(seed.moods, candidate_moods) if seed.moods else 0.5
    style = jaccard(seed.styles, candidate_styles) if seed.styles else 0.5
    genre = jaccard(seed.genres, candidate_genres) if seed.genres else 0.5
    era = era_proximity(seed.year, candidate.year)
    novelty = novelty_score(play_count)

    total_weight = (
        weights.sonic
        + weights.popularity
        + weights.mood
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
        + mood * weights.mood
        + style * weights.style
        + genre * weights.genre
        + era * weights.era
        + novelty * weights.novelty
    ) / total_weight

    return ScoreBreakdown(
        total=total,
        sonic=sonic,
        popularity=popularity,
        mood=mood,
        style=style,
        genre=genre,
        era=era,
        novelty=novelty,
    )
