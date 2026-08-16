"""Recommendation strategies for populating an existing playlist."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from sqlalchemy.orm import Session

from musicseed.db.models import Track
from musicseed.recommender.playlist import Recommendation, recommend_tracks
from musicseed.recommender.scoring import ScoreBreakdown, Weights

PopulateMethod = Literal["average", "frequency"]
"""Playlist populate strategies: ``"average"`` scores against the playlist's
mean profile; ``"frequency"`` aggregates per-track votes."""


def _average_score(scores: list[ScoreBreakdown]) -> ScoreBreakdown:
    count = len(scores)
    return ScoreBreakdown(
        total=sum(s.total for s in scores) / count,
        sonic=sum(s.sonic for s in scores) / count,
        popularity=sum(s.popularity for s in scores) / count,
        style=sum(s.style for s in scores) / count,
        genre=sum(s.genre for s in scores) / count,
        era=sum(s.era for s in scores) / count,
        novelty=sum(s.novelty for s in scores) / count,
    )


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
) -> list[Recommendation]:
    """Recommend tracks voted for by multiple individual playlist tracks.

    Each playlist track is used as its own single-track seed to gather
    candidates. A candidate's score is the average of its per-seed scores
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

    Returns:
        Aggregated recommendations, best first; each recommendation's
        ``sources`` lists the seed track ids that voted for it.
    """
    playlist_ids = set(playlist_track_ids)
    votes: dict[int, list[tuple[int, ScoreBreakdown, Track]]] = defaultdict(list)

    for seed_id in playlist_track_ids:
        _, recs, _ = recommend_tracks(
            session,
            seed_ids=[seed_id],
            limit=per_seed_limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=max_tracks_per_artist,
        )
        for rec in recs:
            if rec.track.id not in playlist_ids:
                votes[rec.track.id].append((seed_id, rec.score, rec.track))

    aggregated = [
        Recommendation(
            track=entries[0][2],
            score=_average_score([score for _, score, _ in entries]),
            sources=[str(seed_id) for seed_id, _, _ in entries],
        )
        for entries in votes.values()
    ]
    aggregated.sort(key=lambda r: (r.score.total, len(r.sources)), reverse=True)

    selected: list[Recommendation] = []
    artist_counts: dict[int | None, int] = defaultdict(int)

    for recommendation in aggregated:
        if min_score is not None and recommendation.score.total < min_score:
            continue
        artist_id = recommendation.track.artist_id
        if artist_counts[artist_id] >= max_tracks_per_artist:
            continue
        selected.append(recommendation)
        artist_counts[artist_id] += 1
        if len(selected) >= limit:
            break

    return selected


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
        )
    raise ValueError(f"Unknown populate method: {method}")
