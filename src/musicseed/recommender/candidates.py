"""Candidate generation for multi-signal recommendations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from musicseed.db.models import Genre, Style, Track, TrackStats
from musicseed.recommender.scoring import SeedProfile


@dataclass
class CandidatePool:
    """Merged candidate IDs and the signal sources that produced each candidate."""

    sources_by_track_id: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))

    def add(self, track_id: int, source: str, seed_ids: set[int]) -> None:
        if track_id not in seed_ids:
            self.sources_by_track_id[track_id].add(source)

    def add_many(self, track_ids: list[int], source: str, seed_ids: set[int]) -> None:
        for track_id in track_ids:
            self.add(track_id, source, seed_ids)

    @property
    def track_ids(self) -> list[int]:
        return list(self.sources_by_track_id.keys())

    def sources_for(self, track_id: int) -> list[str]:
        return sorted(self.sources_by_track_id.get(track_id, set()))


def _limit(base_limit: int, multiplier: int = 4) -> int:
    return max(base_limit * multiplier, 50)


def _ids(query) -> list[int]:
    return [track_id for (track_id,) in query.all()]


def build_candidate_pool(
    session: Session,
    seed: SeedProfile,
    *,
    limit: int,
    year_min: int | None = None,
    year_max: int | None = None,
) -> CandidatePool:
    """Build a candidate pool from all available recommendation signals."""

    pool = CandidatePool()
    candidate_limit = _limit(limit)

    def apply_year_filter(query):
        if year_min is not None:
            query = query.filter(Track.year >= year_min)
        if year_max is not None:
            query = query.filter(Track.year <= year_max)
        return query

    if seed.embedding is not None and seed.embedding_model is not None:
        query = (
            session.query(Track.id)
            .filter(Track.embedding.isnot(None))
            .filter(Track.embedding_model == seed.embedding_model)
            .order_by(Track.embedding.cosine_distance(seed.embedding.tolist()))
            .limit(candidate_limit)
        )
        pool.add_many(_ids(apply_year_filter(query)), "sonic", seed.track_ids)

    if seed.genres:
        query = (
            session.query(Track.id)
            .filter(Track.genres.any(Genre.name.in_(seed.genres)))
            .limit(candidate_limit)
        )
        pool.add_many(_ids(apply_year_filter(query)), "genre", seed.track_ids)

    if seed.styles:
        query = (
            session.query(Track.id)
            .filter(Track.styles.any(Style.name.in_(seed.styles)))
            .limit(candidate_limit)
        )
        pool.add_many(_ids(apply_year_filter(query)), "style", seed.track_ids)

    if seed.year is not None:
        query = (
            session.query(Track.id)
            .filter(Track.year.isnot(None))
            .order_by(func.abs(Track.year - seed.year))
            .limit(candidate_limit)
        )
        pool.add_many(_ids(apply_year_filter(query)), "era", seed.track_ids)

    if seed.popularity is not None:
        popularity_expr = func.coalesce(Track.popularity_score * 100, Track.spotify_popularity)
        query = (
            session.query(Track.id)
            .filter(popularity_expr.isnot(None))
            .order_by(func.abs(popularity_expr - seed.popularity))
            .limit(candidate_limit)
        )
        pool.add_many(_ids(apply_year_filter(query)), "popularity", seed.track_ids)

    novelty_query = (
        session.query(Track.id)
        .outerjoin(TrackStats, TrackStats.track_id == Track.id)
        .order_by(func.coalesce(TrackStats.play_count, 0), Track.id)
        .limit(candidate_limit)
    )
    pool.add_many(_ids(apply_year_filter(novelty_query)), "novelty", seed.track_ids)

    return pool
