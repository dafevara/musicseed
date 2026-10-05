"""Exact constrained top-k scoring of streamed scalar metadata, without ORM graphs."""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from musicseed.db.models import Genre, Style, Track, TrackGenre, TrackStats, TrackStyle
from musicseed.recommender.scoring import (
    ScoreBreakdown,
    SeedProfile,
    SonicCoverage,
    Weights,
    popularity_value,
    prepared_sonic_evidence,
    score_signals,
)
from musicseed.sonic import SonicVectors, prepare_vector

FEATURE_BATCH_SIZE = 500  # Also stays below older SQLite's 999 bind-variable limit.


@dataclass(frozen=True, slots=True)
class ScoredTrack:
    """Only selected IDs, artist identity and explanations survive the scalar scan."""

    id: int
    artist_id: int | None
    score: ScoreBreakdown
    votes: int = 0

    @property
    def rank(self) -> tuple[float, int, int]:
        """Rank by score, frequency vote count where relevant, then lower local ID."""
        return self.score.total, self.votes, -self.id


class ConstrainedTopK:
    """Exact streaming top-k under a per-artist cap, with O(limit) retained scores.

    An incoming track displaces the worst from its artist if that group is full;
    otherwise it displaces the global worst if the selection is full. This is
    the exchange rule for a cardinality-truncated partition constraint and is
    equivalent to globally sorting then applying the same artist cap.
    """

    def __init__(self, limit: int, artist_max: int) -> None:
        """Start an empty constrained selection with positive limits."""
        if limit <= 0 or artist_max <= 0:
            raise ValueError("limit and artist_max must be greater than zero")
        self.limit = limit
        self.artist_max = artist_max
        self.selected: dict[int, ScoredTrack] = {}
        self.by_artist: dict[int | None, set[int]] = defaultdict(set)
        self.heap: list[tuple[tuple[float, int, int], int]] = []

    def add(self, record: ScoredTrack) -> None:
        """Consider one distinct candidate; evicted score objects are not retained."""
        group = self.by_artist.get(record.artist_id, set())
        victim = None
        # Exchange rule: beat the worst of this artist's group if it's full, else the global worst.
        if len(group) >= self.artist_max:
            victim = min((self.selected[i] for i in group), key=lambda r: r.rank)
        elif len(self.selected) >= self.limit:
            # Lazily skip heap entries whose id was already evicted.
            while self.heap[0][1] not in self.selected:
                heapq.heappop(self.heap)
            victim = self.selected[self.heap[0][1]]
        if victim is not None:
            if record.rank <= victim.rank:
                return
            del self.selected[victim.id]
            old_group = self.by_artist[victim.artist_id]
            old_group.remove(victim.id)
            if not old_group:
                del self.by_artist[victim.artist_id]
        self.selected[record.id] = record
        self.by_artist[record.artist_id].add(record.id)
        heapq.heappush(self.heap, (record.rank, record.id))
        # Stale heap keys contain no scores; compact them to bound even those keys.
        if len(self.heap) > 2 * self.limit:
            self.heap = [(r.rank, r.id) for r in self.selected.values()]
            heapq.heapify(self.heap)

    def results(self) -> list[ScoredTrack]:
        """Return the exact selected set in deterministic descending rank order."""
        return sorted(self.selected.values(), key=lambda r: r.rank, reverse=True)


def score_eligible_tracks(
    session: Session,
    seed: SeedProfile,
    vectors: SonicVectors,
    *,
    limit: int,
    weights: Weights,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    exclude_ids: set[int] | None = None,
) -> tuple[list[ScoredTrack], SonicCoverage]:
    """Score one profile using the shared batched candidate scan."""
    selections, coverage = score_eligible_profiles(
        session, [seed], vectors, limit=limit, weights=weights,
        year_min=year_min, year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist, min_score=min_score,
        exclude_ids=exclude_ids,
    )
    return selections[0], coverage


def score_eligible_profiles(
    session: Session,
    seeds: Sequence[SeedProfile],
    vectors: SonicVectors,
    *,
    limit: int,
    weights: Weights,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    exclude_ids: set[int] | None = None,
) -> tuple[list[list[ScoredTrack]], SonicCoverage]:
    """Read each candidate batch once and retain exact top-k for every profile.

    All profile seeds are excluded before tag reads and per-profile selection.
    Memory retains one metadata/tag batch and at most limit scores per profile.
    """
    profiles = [
        (seed, prepare_vector(seed.embedding), ConstrainedTopK(limit, max_tracks_per_artist))
        for seed in seeds
    ]
    if not profiles:
        return [], SonicCoverage(candidates=0, with_vector=0)
    excluded = set(exclude_ids or set()).union(*(seed.track_ids for seed in seeds))
    query = (
        select(
            Track.id,
            Track.artist_id,
            Track.plex_id,
            Track.year,
            Track.popularity_score,
            Track.spotify_popularity,
            TrackStats.play_count,
        )
        .outerjoin(TrackStats, TrackStats.track_id == Track.id)
        .order_by(Track.id)
    )
    if year_min is not None:
        query = query.where(Track.year >= year_min)
    if year_max is not None:
        query = query.where(Track.year <= year_max)
    count = with_vector = 0
    for batch in session.execute(
        query.execution_options(yield_per=FEATURE_BATCH_SIZE)
    ).partitions():
        rows = [row for row in batch if row.id not in excluded]
        if not rows:
            continue
        ids = [row.id for row in rows]
        # Fetch tag names for the whole batch in two joins, then map them back per track.
        styles: dict[int, set[str]] = defaultdict(set)
        genres: dict[int, set[str]] = defaultdict(set)
        for track_id, name in session.execute(
            select(TrackStyle.track_id, Style.name).join(Style).where(TrackStyle.track_id.in_(ids))
        ):
            styles[track_id].add(name)
        for track_id, name in session.execute(
            select(TrackGenre.track_id, Genre.name).join(Genre).where(TrackGenre.track_id.in_(ids))
        ):
            genres[track_id].add(name)
        for row in rows:
            # Score from scalar facts; the top-k keeps only the best under the artist cap.
            vector = vectors.get_prepared(row.plex_id)
            count += 1
            with_vector += vector is not None
            popularity = popularity_value(row.popularity_score, row.spotify_popularity)
            track_id, artist_id, year, play_count = (
                row.id, row.artist_id, row.year, row.play_count,
            )
            candidate_styles, candidate_genres = styles[track_id], genres[track_id]
            for seed, seed_vector, selected in profiles:
                score = score_signals(
                    candidate_styles=candidate_styles,
                    candidate_genres=candidate_genres,
                    play_count=play_count,
                    candidate_vector=None,
                    candidate_popularity=popularity,
                    candidate_year=year,
                    seed=seed,
                    weights=weights,
                    sonic_evidence=prepared_sonic_evidence(vector, seed_vector),
                )
                if min_score is None or score.total >= min_score:
                    selected.add(ScoredTrack(track_id, artist_id, score))
    return (
        [selected.results() for _, _, selected in profiles],
        SonicCoverage(candidates=count, with_vector=with_vector),
    )
