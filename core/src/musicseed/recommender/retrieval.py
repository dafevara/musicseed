"""Exact constrained top-k scoring of streamed scalar metadata, without ORM graphs."""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from musicseed.db.models import Genre, Style, Track, TrackGenre, TrackStats, TrackStyle
from musicseed.recommender.scoring import (
    ScoreBreakdown,
    SeedProfile,
    SonicCoverage,
    Weights,
    has_usable_vector,
    popularity_value,
    score_signals,
)
from musicseed.sonic import SonicVectors

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
        if len(group) >= self.artist_max:
            victim = min((self.selected[i] for i in group), key=lambda r: r.rank)
        elif len(self.selected) >= self.limit:
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
    """Filter years, exclude all seeds, score scalar batches and retain exact top-k.

    No candidate budget truncates eligibility. SQL reads only scoring columns,
    stats and tag names. Seeds are excluded before tags/scoring/selection, using
    membership rather than an unbounded SQL IN list. The caller materializes
    only the final selected tracks. No artist/album/mood/history graphs are read.
    """
    selected = ConstrainedTopK(limit, max_tracks_per_artist)
    excluded = seed.track_ids | (exclude_ids or set())
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
            vector = vectors.get(row.plex_id)
            count += 1
            with_vector += has_usable_vector(vector)
            popularity = popularity_value(row.popularity_score, row.spotify_popularity)
            score = score_signals(
                candidate_styles=styles[row.id],
                candidate_genres=genres[row.id],
                play_count=row.play_count,
                candidate_vector=vector,
                candidate_popularity=popularity,
                candidate_year=row.year,
                seed=seed,
                weights=weights,
            )
            if min_score is None or score.total >= min_score:
                selected.add(ScoredTrack(row.id, row.artist_id, score))
    return selected.results(), SonicCoverage(candidates=count, with_vector=with_vector)
