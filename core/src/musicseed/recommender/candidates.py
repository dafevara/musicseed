"""Candidate generation for multi-signal recommendations."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from musicseed.db.models import Genre, Style, Track, TrackStats
from musicseed.recommender.scoring import SeedProfile
from musicseed.sonic import SonicVectors


class CandidatePool(BaseModel):
    """Merged candidate IDs and the signal sources that produced each candidate."""

    sources_by_track_id: dict[int, set[str]] = Field(default_factory=dict)

    def add(self, track_id: int, source: str, seed_ids: set[int]) -> None:
        if track_id not in seed_ids:
            self.sources_by_track_id.setdefault(track_id, set()).add(source)

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
    vectors: SonicVectors,
    *,
    limit: int,
    year_min: int | None = None,
    year_max: int | None = None,
) -> CandidatePool:
    """Build a candidate pool from all available recommendation signals."""

    pool = CandidatePool()
    candidate_limit = _limit(limit)

    def collect(query, source: str) -> None:
        """Narrow a source query to the year window, bound it, and pool the results.

        The year filter has to be applied before ``limit`` — SQLAlchemy rejects
        ``filter()`` on an already-limited query, and filtering after the fact
        would trim an already-truncated set rather than search within the window.
        """
        if year_min is not None:
            query = query.filter(Track.year >= year_min)
        if year_max is not None:
            query = query.filter(Track.year <= year_max)
        pool.add_many(_ids(query.limit(candidate_limit)), source, seed.track_ids)

    if seed.embedding is not None:
        # Sonic ranking happens in memory over Plex's vectors; the year window is
        # still applied in SQL so it constrains this source like the others.
        nearest_plex_ids = vectors.nearest(seed.embedding, candidate_limit)
        if nearest_plex_ids:
            collect(
                session.query(Track.id).filter(Track.plex_id.in_(nearest_plex_ids)),
                "sonic",
            )

    if seed.genres:
        collect(
            session.query(Track.id).filter(Track.genres.any(Genre.name.in_(seed.genres))),
            "genre",
        )

    if seed.styles:
        collect(
            session.query(Track.id).filter(Track.styles.any(Style.name.in_(seed.styles))),
            "style",
        )

    if seed.year is not None:
        collect(
            session.query(Track.id)
            .filter(Track.year.isnot(None))
            .order_by(func.abs(Track.year - seed.year)),
            "era",
        )

    if seed.popularity is not None:
        popularity_expr = func.coalesce(Track.popularity_score * 100, Track.spotify_popularity)
        collect(
            session.query(Track.id)
            .filter(popularity_expr.isnot(None))
            .order_by(func.abs(popularity_expr - seed.popularity)),
            "popularity",
        )

    collect(
        session.query(Track.id)
        .outerjoin(TrackStats, TrackStats.track_id == Track.id)
        .order_by(func.coalesce(TrackStats.play_count, 0), Track.id),
        "novelty",
    )

    return pool
