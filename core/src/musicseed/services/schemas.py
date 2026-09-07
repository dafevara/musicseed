"""JSON-safe DTOs returned by core services.

These are the stable shapes core services hand to surfaces (CLI, API, future
MCP). They carry no SQLAlchemy objects, so a caller never depends on ORM
loading strategy or session lifetime.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from musicseed.db.models import Track
from musicseed.recommender.playlist import Recommendation
from musicseed.recommender.scoring import ScoreBreakdown, track_popularity_value


class ServiceTrack(BaseModel):
    """A track projected from the ORM into a stable, JSON-safe shape."""

    model_config = {"frozen": True}

    id: int
    title: str
    artist: str | None
    album: str | None
    year: int | None
    popularity: float | None  # 0-100 scale, or None when unknown
    plex_id: int | None


class ServiceRecommendation(BaseModel):
    """A scored recommendation with its track, breakdown, and candidate sources."""

    model_config = {"frozen": True}

    track: ServiceTrack
    score: ScoreBreakdown
    sources: list[str] = Field(default_factory=list)


def to_service_track(track: Track) -> ServiceTrack:
    """Project an ORM ``Track`` into a ``ServiceTrack``.

    Call while the track's artist/album relationships are still loaded (i.e.
    inside the session that produced it).
    """
    return ServiceTrack(
        id=track.id,
        title=track.title,
        artist=track.artist.name if track.artist else None,
        album=track.album.title if track.album else None,
        year=track.year,
        popularity=track_popularity_value(track),
        plex_id=track.plex_id,
    )


def to_service_recommendation(rec: Recommendation) -> ServiceRecommendation:
    """Project a recommender ``Recommendation`` into a ``ServiceRecommendation``."""
    return ServiceRecommendation(
        track=to_service_track(rec.track),
        score=rec.score,
        sources=list(rec.sources),
    )
