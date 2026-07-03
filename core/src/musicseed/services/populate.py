"""Populate service — fill an existing Plex playlist with complementary recommendations."""

from pydantic import BaseModel

from musicseed.clients.plex_api import PlaylistResult, PlexClient
from musicseed.config import get_config
from musicseed.db.models import Track
from musicseed.db.session import get_session
from musicseed.exceptions import ConfigurationError, NotFoundError
from musicseed.recommender.playlist import Recommendation
from musicseed.recommender.populate import PopulateMethod, populate_playlist_recommendations
from musicseed.recommender.scoring import Weights


class PopulateResult(BaseModel):
    """Result of a populate preview request."""

    model_config = {"arbitrary_types_allowed": True}

    playlist_name: str
    playlist_track_count: int
    matched_track_count: int
    recommendations: list[Recommendation]


class PopulateApplyResult(PopulateResult):
    """Result of a populate request that was written to Plex."""

    added_count: int


def _plex_client() -> PlexClient:
    config = get_config()
    if not config.plex.token:
        raise ConfigurationError(
            "plex.token is not configured. Add it to your config file."
        )
    return PlexClient(base_url=config.plex.url, token=config.plex.token)


def list_plex_playlists() -> list[PlaylistResult]:
    """Return every audio playlist currently on the Plex server."""
    return _plex_client().list_playlists()


def _resolve_playlist_local_tracks(
    client: PlexClient, session, playlist_name: str
) -> tuple[str, int, list[int]]:
    """Return (rating_key, plex track count, local track ids) for a Plex playlist.

    Raises NotFoundError if the playlist doesn't exist or none of its tracks
    are present in the local database.
    """
    rating_key = client.find_playlist(playlist_name)
    if rating_key is None:
        raise NotFoundError(f"No Plex playlist named '{playlist_name}' was found.")

    plex_ids = client.get_playlist_tracks(rating_key)
    if not plex_ids:
        raise NotFoundError(f"Playlist '{playlist_name}' has no tracks in Plex.")

    local_ids = [
        track_id
        for (track_id,) in session.query(Track.id).filter(Track.plex_id.in_(plex_ids))
    ]
    if not local_ids:
        raise NotFoundError(
            f"None of the tracks in playlist '{playlist_name}' are in the local "
            "library. Import and enrich them first."
        )
    return rating_key, len(plex_ids), local_ids


def get_populate_recommendations(
    playlist_name: str,
    *,
    method: PopulateMethod = "average",
    limit: int = 10,
    per_seed_limit: int = 30,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> PopulateResult:
    """Preview complementary recommendations for an existing Plex playlist."""
    client = _plex_client()
    with get_session() as session:
        _, plex_track_count, local_ids = _resolve_playlist_local_tracks(
            client, session, playlist_name
        )
        recommendations = populate_playlist_recommendations(
            session,
            local_ids,
            method=method,
            limit=limit,
            per_seed_limit=per_seed_limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=max_tracks_per_artist,
            min_score=min_score,
        )

        return PopulateResult(
            playlist_name=playlist_name,
            playlist_track_count=plex_track_count,
            matched_track_count=len(local_ids),
            recommendations=recommendations,
        )


def populate_playlist(
    playlist_name: str,
    *,
    method: PopulateMethod = "average",
    limit: int = 10,
    per_seed_limit: int = 30,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> PopulateApplyResult:
    """Generate recommendations and add them to an existing Plex playlist.

    Raises:
        ConfigurationError: if plex.token is not configured.
        NotFoundError: if the playlist or its local tracks cannot be resolved.
        PlexAPIError: if the Plex API call fails.
    """
    client = _plex_client()
    with get_session() as session:
        rating_key, plex_track_count, local_ids = _resolve_playlist_local_tracks(
            client, session, playlist_name
        )
        recommendations = populate_playlist_recommendations(
            session,
            local_ids,
            method=method,
            limit=limit,
            per_seed_limit=per_seed_limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=max_tracks_per_artist,
            min_score=min_score,
        )

        plex_ids = [
            rec.track.plex_id for rec in recommendations if rec.track.plex_id is not None
        ]
        if plex_ids:
            client.add_to_playlist(rating_key, plex_ids)

        return PopulateApplyResult(
            playlist_name=playlist_name,
            playlist_track_count=plex_track_count,
            matched_track_count=len(local_ids),
            recommendations=recommendations,
            added_count=len(plex_ids),
        )
