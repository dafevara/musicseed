"""Populate service — fill an existing Plex playlist with complementary recommendations."""

from pydantic import BaseModel

from musicseed.clients.plex import Playlist, PlexClient
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


def list_plex_playlists() -> list[Playlist]:
    """Return every audio playlist currently on the Plex server."""
    return _plex_client().list_playlists()


def _plex_ids_for_track_ids(session, track_ids: list[int]) -> list[int]:
    """Map local track ids to Plex rating keys, preserving input order."""
    if not track_ids:
        return []
    rows = (
        session.query(Track.id, Track.plex_id)
        .filter(Track.id.in_(track_ids), Track.plex_id.is_not(None))
        .all()
    )
    by_id = {track_id: plex_id for track_id, plex_id in rows}
    seen: set[int] = set()
    plex_ids: list[int] = []
    for track_id in track_ids:
        plex_id = by_id.get(track_id)
        if plex_id is not None and plex_id not in seen:
            seen.add(plex_id)
            plex_ids.append(plex_id)
    return plex_ids


def _resolve_playlist_local_tracks(
    client: PlexClient, session, playlist_name: str
) -> tuple[str, int, list[int]]:
    """Return (rating_key, plex track count, local track ids) for a Plex playlist.

    Raises NotFoundError if the playlist doesn't exist or none of its tracks
    are present in the local database.
    """
    playlist = client.find_playlist(playlist_name)
    if playlist is None:
        raise NotFoundError(f"No Plex playlist named '{playlist_name}' was found.")

    items = client.get_playlist_tracks(playlist.rating_key)
    if not items:
        raise NotFoundError(f"Playlist '{playlist_name}' has no tracks in Plex.")

    plex_ids = [int(i.rating_key) for i in items]
    local_ids = [
        track_id
        for (track_id,) in session.query(Track.id).filter(Track.plex_id.in_(plex_ids))
    ]
    if not local_ids:
        raise NotFoundError(
            f"None of the tracks in playlist '{playlist_name}' are in the local "
            "library. Import and enrich them first."
        )
    return playlist.rating_key, len(plex_ids), local_ids


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
    track_ids: list[int] | None = None,
) -> PopulateApplyResult:
    """Generate recommendations and add them to an existing Plex playlist.

    When ``track_ids`` is provided, only those local track ids are added (the
    recommendation step is skipped). This supports surfaces that let a user
    prune a preview before confirming.

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

        if track_ids is not None:
            recommendations: list[Recommendation] = []
            plex_ids = _plex_ids_for_track_ids(session, track_ids)
        else:
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
                rec.track.plex_id
                for rec in recommendations
                if rec.track.plex_id is not None
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
