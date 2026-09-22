"""Populate service — fill an existing Plex playlist with complementary recommendations."""

from pydantic import BaseModel

from musicseed.clients.plex import Playlist, PlexClient
from musicseed.context import MusicSeedContext, get_context
from musicseed.db.models import Track
from musicseed.exceptions import ConfigurationError, NotFoundError
from musicseed.recommender.playlist import Recommendation
from musicseed.recommender.populate import PopulateMethod, populate_playlist_recommendations
from musicseed.recommender.scoring import Weights
from musicseed.services.playlist_tracks import resolve_track_selection
from musicseed.services.schemas import ServiceRecommendation, to_service_recommendation


class PopulateResult(BaseModel):
    """Result of a populate preview request."""

    playlist_id: str
    playlist_name: str
    playlist_track_count: int
    matched_track_count: int
    recommendations: list[ServiceRecommendation]


class PopulateApplyResult(PopulateResult):
    """Result of a populate request that was written to Plex."""

    added_count: int
    already_present_count: int = 0


def _plex_client(context: MusicSeedContext | None = None) -> PlexClient:
    config = (context or get_context()).config
    if not config.plex.token:
        raise ConfigurationError(
            "plex.token is not configured. Add it to your config file."
        )
    return PlexClient(base_url=config.plex.url, token=config.plex.token)


def list_plex_playlists(context: MusicSeedContext | None = None) -> list[Playlist]:
    """Return every audio playlist currently on the Plex server.

    Args:
        context: runtime context to use; defaults to the default context.

    Returns:
        All audio playlists on the server.

    Raises:
        ConfigurationError: if plex.token is not configured.
        PlexAPIError: if the Plex API call fails.
    """
    return _plex_client(context).list_playlists()


def _plex_ids_for_track_ids(session, track_ids: list[int]) -> list[int]:
    """Map all approved IDs in order; stale/unmapped IDs reject the whole write."""
    return [track.plex_id for track in resolve_track_selection(session, track_ids)]


def _existing_plex_ids(client: PlexClient, rating_key: str) -> set[int]:
    """Return the Plex track ratingKeys currently in a playlist."""
    return {int(i.rating_key) for i in client.get_playlist_tracks(str(rating_key))}


def _resolve_playlist_local_tracks(
    client: PlexClient, session, playlist_id: str
) -> tuple[Playlist, int, list[int]]:
    """Return (playlist, plex track count, local track ids) for a Plex playlist.

    Raises NotFoundError if the playlist doesn't exist or none of its tracks
    are present in the local database.
    """
    playlist = client.get_playlist(str(playlist_id))
    if playlist is None:
        raise NotFoundError(f"No Plex playlist with id '{playlist_id}' was found.")

    items = client.get_playlist_tracks(playlist.rating_key)
    if not items:
        raise NotFoundError(f"Playlist '{playlist.title}' has no tracks in Plex.")

    plex_ids = [int(i.rating_key) for i in items]
    local_ids = [
        track_id
        for (track_id,) in session.query(Track.id).filter(Track.plex_id.in_(plex_ids))
    ]
    if not local_ids:
        raise NotFoundError(
            f"None of the tracks in playlist '{playlist.title}' are in the local "
            "library. Import and enrich them first."
        )
    return playlist, len(plex_ids), local_ids


def get_populate_recommendations(
    playlist_id: str,
    *,
    method: PopulateMethod = "average",
    limit: int = 10,
    per_seed_limit: int = 30,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    context: MusicSeedContext | None = None,
) -> PopulateResult:
    """Preview complementary recommendations for an existing Plex playlist.

    Args:
        playlist_id: Plex rating key of the playlist to populate.
        method: populate strategy (see ``PopulateMethod``).
        limit: maximum number of recommendations to return.
        per_seed_limit: candidates gathered per playlist track ("frequency"
            method only).
        weights: signal weights; defaults to ``Weights()``.
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap applied during selection.
        min_score: drop recommendations with a total score below this value.
        context: runtime context to use; defaults to the default context.

    Returns:
        The playlist identity, how many of its tracks matched the local
        library, and the previewed recommendations. Nothing is written to
        Plex.

    Raises:
        ConfigurationError: if plex.token is not configured.
        NotFoundError: if the playlist doesn't exist or none of its tracks
            are in the local library.
        PlexAPIError: if the Plex API call fails.
    """
    ctx = context or get_context()
    client = _plex_client(ctx)
    with ctx.session() as session:
        playlist, plex_track_count, local_ids = _resolve_playlist_local_tracks(
            client, session, playlist_id
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
            vectors=ctx.sonic_vectors,
        )

        return PopulateResult(
            playlist_id=playlist.rating_key,
            playlist_name=playlist.title,
            playlist_track_count=plex_track_count,
            matched_track_count=len(local_ids),
            recommendations=[
                to_service_recommendation(r) for r in recommendations
            ],
        )


def populate_playlist(
    playlist_id: str,
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
    context: MusicSeedContext | None = None,
) -> PopulateApplyResult:
    """Generate recommendations and add them to an existing Plex playlist.

    When ``track_ids`` is provided, only those local track ids are added (the
    recommendation step is skipped). This supports surfaces that let a user
    prune a preview before confirming.

    Args:
        playlist_id: Plex rating key of the playlist to populate.
        method: populate strategy (see ``PopulateMethod``).
        limit: maximum number of recommendations to add.
        per_seed_limit: candidates gathered per playlist track ("frequency"
            method only).
        weights: signal weights; defaults to ``Weights()``.
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap applied during selection.
        min_score: drop recommendations with a total score below this value.
        track_ids: explicit local track ids to add instead of recommending.
        context: runtime context to use; defaults to the default context.

    Returns:
        The playlist identity, match counts, the recommendations (empty when
        ``track_ids`` was given), and how many tracks were actually added.

    Raises:
        ConfigurationError: if plex.token is not configured.
        NotFoundError: if the playlist or its local tracks cannot be resolved.
        PlexAPIError: if the Plex API call fails.
    """
    ctx = context or get_context()
    client = _plex_client(ctx)
    with ctx.session() as session:
        playlist, plex_track_count, local_ids = _resolve_playlist_local_tracks(
            client, session, playlist_id
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
                vectors=ctx.sonic_vectors,
            )
            plex_ids = [
                rec.track.plex_id
                for rec in recommendations
                if rec.track.plex_id is not None
            ]

        added_plex_ids: list[int] = []
        already_present: int = 0
        if plex_ids:
            existing_ids = _existing_plex_ids(client, playlist.rating_key)
            added_plex_ids = [pid for pid in plex_ids if pid not in existing_ids]
            already_present = len(plex_ids) - len(added_plex_ids)
            if added_plex_ids:
                client.add_to_playlist(playlist.rating_key, added_plex_ids)

        return PopulateApplyResult(
            playlist_id=playlist.rating_key,
            playlist_name=playlist.title,
            playlist_track_count=plex_track_count,
            matched_track_count=len(local_ids),
            recommendations=[
                to_service_recommendation(r) for r in recommendations
            ],
            added_count=len(added_plex_ids),
            already_present_count=already_present,
        )
