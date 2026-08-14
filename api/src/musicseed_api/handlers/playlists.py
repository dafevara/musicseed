"""Playlist orchestration — list, create, and populate Plex playlists."""

from __future__ import annotations

from musicseed.recommender.populate import PopulateMethod
from musicseed.recommender.scoring import Weights
from musicseed.services.populate import (
    PopulateApplyResult,
    PopulateResult,
    get_populate_recommendations,
    list_plex_playlists,
    populate_playlist,
)
from musicseed.services.recommend import PlaylistCreateResult, create_playlist


def get_playlists() -> list[dict]:
    """List Plex playlists with track counts."""
    playlists = list_plex_playlists()
    return [
        {
            "name": p.title,
            "rating_key": p.rating_key,
            "track_count": p.leaf_count,
        }
        for p in playlists
    ]


def create_playlist_from_seeds(
    name: str,
    seed_ids: list[int],
    limit: int = 50,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
) -> dict:
    """Create a new Plex playlist from seed track recommendations."""
    result: PlaylistCreateResult = create_playlist(
        name=name,
        seed_ids=seed_ids,
        limit=limit,
        weights=weights,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
    )
    return {
        "name": result.playlist.title if result.playlist else name,
        "track_count": result.playlist.leaf_count if result.playlist else 0,
        "seed_count": len(result.seed_tracks),
        "recommendation_count": len(result.recommendations),
    }


def preview_populate(
    playlist_id: str,
    limit: int = 10,
    method: PopulateMethod = "average",
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
) -> dict:
    """Preview complementary recommendations for an existing playlist."""
    result: PopulateResult = get_populate_recommendations(
        playlist_id=playlist_id,
        method=method,
        limit=limit,
        weights=weights,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
    )
    return {
        "playlist_id": result.playlist_id,
        "playlist_name": result.playlist_name,
        "method": method,
        "playlist_track_count": result.playlist_track_count,
        "matched_track_count": result.matched_track_count,
        "weights": (weights or Weights()).model_dump(),
        "recommendations": [
            {
                "track_id": r.track.id,
                "title": r.track.title,
                "artist": r.track.artist.name if r.track.artist else None,
                "score": r.score.model_dump() if hasattr(r.score, "model_dump") else r.score,
            }
            for r in result.recommendations
        ],
    }


def apply_populate(
    playlist_id: str,
    limit: int = 10,
    method: PopulateMethod = "average",
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    track_ids: list[int] | None = None,
) -> dict:
    """Generate recommendations and add them to an existing Plex playlist.

    When ``track_ids`` is provided, only those tracks are added and the
    recommendation step is skipped.
    """
    result: PopulateApplyResult = populate_playlist(
        playlist_id=playlist_id,
        method=method,
        limit=limit,
        weights=weights,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        track_ids=track_ids,
    )
    return {
        "playlist_id": result.playlist_id,
        "playlist_name": result.playlist_name,
        "playlist_track_count": result.playlist_track_count,
        "matched_track_count": result.matched_track_count,
        "added_count": result.added_count,
    }
