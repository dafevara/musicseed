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
        """Record that ``source`` produced ``track_id`` as a candidate.

        Seed tracks are silently skipped — seeds are never their own
        candidates.

        Args:
            track_id: local id of the candidate track.
            source: name of the signal source (e.g. ``"sonic"``, ``"genre"``).
            seed_ids: ids of the seed tracks to exclude.
        """
        if track_id not in seed_ids:
            self.sources_by_track_id.setdefault(track_id, set()).add(source)

    def add_many(self, track_ids: list[int], source: str, seed_ids: set[int]) -> None:
        """Record several candidate ids from one source (see ``add``).

        Args:
            track_ids: local ids of the candidate tracks.
            source: name of the signal source that produced them.
            seed_ids: ids of the seed tracks to exclude.
        """
        for track_id in track_ids:
            self.add(track_id, source, seed_ids)

    @property
    def track_ids(self) -> list[int]:
        """All distinct candidate track ids in the pool."""
        return list(self.sources_by_track_id.keys())

    def sources_for(self, track_id: int) -> list[str]:
        """Return the sorted source names that produced a candidate.

        Args:
            track_id: local id of the candidate track.

        Returns:
            Sorted source names, or an empty list for an unknown id.
        """
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
    """Build a candidate pool from all available recommendation signals.

    Each signal contributes its own bounded query (capped at
    ``max(limit * 4, 50)`` ids) so the pool is a generous superset that the
    scorer later trims — sources are only included when the seed profile has
    data for them:

    * ``sonic`` — nearest neighbors of the seed embedding in Plex's vectors
      (ranked in memory; the year window is still applied in SQL),
    * ``genre`` / ``style`` — tracks sharing any seed genre/style,
    * ``era`` — tracks closest to the seed year,
    * ``popularity`` — tracks closest to the seed popularity,
    * ``novelty`` — least-played tracks first (always included).

    The year window filters every source before its limit is applied, so a
    narrow window searches within the window rather than truncating after
    the fact. Seed tracks are excluded by ``CandidatePool.add``.

    Args:
        session: open database session.
        seed: the aggregated seed profile.
        vectors: the query-time Plex sonic vector store.
        limit: requested number of final recommendations; per-source queries
            are bounded to a multiple of this.
        year_min: only consider tracks released in this year or later.
        year_max: only consider tracks released in this year or earlier.

    Returns:
        The merged candidate pool, recording which sources produced each
        candidate.
    """
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
