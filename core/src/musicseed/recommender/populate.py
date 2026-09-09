"""Recommendation strategies for populating an existing playlist."""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from musicseed.recommender.playlist import Recommendation, recommend_tracks
from musicseed.recommender.scoring import Weights
from musicseed.sonic import SonicVectors

PopulateMethod = Literal["average", "frequency"]
"""Playlist populate strategies: ``"average"`` scores against the playlist's
mean profile; ``"frequency"`` aggregates per-track votes."""


def populate_average(
    session: Session,
    playlist_track_ids: list[int],
    *,
    limit: int,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    vectors: SonicVectors | None = None,
) -> list[Recommendation]:
    """Recommend tracks against the mean sonic/metadata profile of a playlist.

    Tracks already in the playlist are excluded automatically because they are
    the seed set, and `recommend_tracks` never returns seed tracks.

    Args:
        session: open database session.
        playlist_track_ids: local ids of the playlist's tracks, used as seeds.
        limit: maximum number of recommendations to return.
        weights: signal weights; defaults to ``Weights()``.
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap applied during selection.
        min_score: drop recommendations with a total score below this value.
        vectors: Plex sonic vectors to score against; defaults to the default
            context's cached vectors.

    Returns:
        Scored recommendations, best first.
    """
    _, recommendations, _ = recommend_tracks(
        session,
        seed_ids=playlist_track_ids,
        limit=limit,
        weights=weights,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
        vectors=vectors,
    )
    return recommendations


def populate_frequency(
    session: Session,
    playlist_track_ids: list[int],
    *,
    limit: int,
    per_seed_limit: int = 30,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    vectors: SonicVectors | None = None,
) -> list[Recommendation]:
    """Recommend tracks voted for by multiple individual playlist tracks.

    Each distinct playlist track is used as its own single-track seed to score
    all eligible candidates. The entire playlist is excluded before per-seed
    vote budgets, and one vector-cache snapshot is reused for the request.
    This costs one scalar scan per seed; prefer average mode for large playlists.
    A candidate's score is the average of its per-seed scores
    across every seed that recommended it (its "votes"); results are ranked
    by that average score, with vote count as a tiebreaker, so --limit cuts
    at the highest-scoring candidates. This avoids a literal set-intersection
    across seeds, which collapses to empty once a playlist has more than a
    handful of tracks.

    Args:
        session: open database session.
        playlist_track_ids: local ids of the playlist's tracks, each used as
            an individual seed.
        limit: maximum number of recommendations to return.
        per_seed_limit: candidates gathered per playlist track.
        weights: signal weights; defaults to ``Weights()``.
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap applied during selection.
        min_score: drop recommendations with a total score below this value.
        vectors: Plex sonic vectors to score against; defaults to the default
            context's cached vectors.

    Returns:
        Aggregated recommendations, best first; each recommendation's
        ``sources`` lists the seed track ids that voted for it.
    """
    if per_seed_limit <= 0:
        raise ValueError("per_seed_limit must be greater than zero")
    if not playlist_track_ids:
        return []
    _, recommendations, _ = recommend_tracks(
        session,
        seed_ids=playlist_track_ids,
        limit=limit,
        method="frequency",
        per_seed_limit=per_seed_limit,
        weights=weights,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
        vectors=vectors,
    )
    return recommendations


def populate_playlist_recommendations(
    session: Session,
    playlist_track_ids: list[int],
    *,
    method: PopulateMethod = "average",
    limit: int = 10,
    per_seed_limit: int = 30,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    vectors: SonicVectors | None = None,
) -> list[Recommendation]:
    """Dispatch to the requested populate strategy.

    Args:
        session: open database session.
        playlist_track_ids: local ids of the playlist's tracks.
        method: ``"average"`` or ``"frequency"`` (see ``PopulateMethod``).
        limit: maximum number of recommendations to return.
        per_seed_limit: candidates gathered per playlist track ("frequency"
            method only).
        weights: signal weights; defaults to ``Weights()``.
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap applied during selection.
        min_score: drop recommendations with a total score below this value.
        vectors: Plex sonic vectors to score against; defaults to the default
            context's cached vectors.

    Returns:
        Scored recommendations, best first.

    Raises:
        ValueError: if ``method`` is not a known populate strategy.
    """
    if method == "average":
        return populate_average(
            session,
            playlist_track_ids,
            limit=limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=max_tracks_per_artist,
            min_score=min_score,
            vectors=vectors,
        )
    if method == "frequency":
        return populate_frequency(
            session,
            playlist_track_ids,
            limit=limit,
            per_seed_limit=per_seed_limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=max_tracks_per_artist,
            min_score=min_score,
            vectors=vectors,
        )
    raise ValueError(f"Unknown populate method: {method}")
