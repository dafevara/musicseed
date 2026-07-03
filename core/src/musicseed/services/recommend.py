"""Recommendation service — surface-agnostic entry points for the recommendation flow."""

from pydantic import BaseModel

from musicseed.clients.plex_api import PlaylistResult, PlexClient
from musicseed.config import get_config
from musicseed.db.models import Track
from musicseed.db.session import get_session
from musicseed.exceptions import ConfigurationError, NotFoundError
from musicseed.recommender.playlist import Recommendation, recommend_tracks
from musicseed.recommender.scoring import Weights


class RecommendationResult(BaseModel):
    """Result of a recommendation request."""

    model_config = {"arbitrary_types_allowed": True}

    seed_tracks: list[Track]
    recommendations: list[Recommendation]


class PlaylistCreateResult(BaseModel):
    """Result of a playlist creation request."""

    model_config = {"arbitrary_types_allowed": True}

    seed_tracks: list[Track]
    recommendations: list[Recommendation]
    playlist: PlaylistResult


def get_recommendations(
    *,
    seed_texts: list[str] | None = None,
    seed_ids: list[int] | None = None,
    limit: int = 50,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> RecommendationResult:
    """Return seed tracks and scored recommendations.

    Raises:
        NotFoundError: if one or more seed tracks cannot be resolved.
    """
    try:
        with get_session() as session:
            seed_tracks, recommendations = recommend_tracks(
                session,
                seed_texts=seed_texts,
                seed_ids=seed_ids,
                limit=limit,
                weights=weights,
                year_min=year_min,
                year_max=year_max,
                max_tracks_per_artist=max_tracks_per_artist,
                min_score=min_score,
            )
        return RecommendationResult(seed_tracks=seed_tracks, recommendations=recommendations)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc


def create_playlist(
    name: str,
    *,
    seed_texts: list[str] | None = None,
    seed_ids: list[int] | None = None,
    limit: int = 50,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> PlaylistCreateResult:
    """Generate recommendations and create a Plex playlist.

    Raises:
        ConfigurationError: if plex.token is not configured.
        NotFoundError: if seed tracks cannot be resolved.
        PlexAPIError: if the Plex API call fails.
    """
    config = get_config()
    if not config.plex.token:
        raise ConfigurationError(
            "plex.token is not configured. Add it to your config file."
        )

    result = get_recommendations(
        seed_texts=seed_texts,
        seed_ids=seed_ids,
        limit=limit,
        weights=weights,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
    )

    plex_ids = [t.plex_id for t in result.seed_tracks if t.plex_id is not None] + [
        rec.track.plex_id for rec in result.recommendations if rec.track.plex_id is not None
    ]

    client = PlexClient(base_url=config.plex.url, token=config.plex.token)
    playlist = client.create_playlist(name, plex_ids)

    return PlaylistCreateResult(
        seed_tracks=result.seed_tracks,
        recommendations=result.recommendations,
        playlist=playlist,
    )
