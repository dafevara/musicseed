"""Playlist orchestration — list, create, and populate Plex playlists."""

from __future__ import annotations

from musicseed.recommender.populate import PopulateMethod
from musicseed.recommender.scoring import Weights
from musicseed.services.playlist_tracks import create_playlist_from_tracks
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
    track_ids: list[int] | None = None,
) -> dict:
    """Run the playlist-create story line, from approved IDs or a fresh selection.

    When ``track_ids`` is provided, the approved selection (seeds + chosen
    recommendations) is written verbatim in order via core's
    ``create_playlist_from_tracks`` — no re-scoring, no re-filtering.
    Otherwise a selection is generated from the seeds via core's
    ``create_playlist`` (generate-and-write) and the resulting playlist is
    reported.

    Args:
        name: playlist title.
        seed_ids: local seed track ids.
        limit: maximum recommendations when generating a selection.
        weights: signal weights; defaults to the "balanced" preset.
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap during selection.
        track_ids: approved local track ids to write verbatim; when set, the
            recommendation step is skipped.

    Returns:
        A wire-ready dict with the playlist name, track count, seed count,
        and recommendation count.
    """
    if track_ids is not None:
        seeds = list(dict.fromkeys(seed_ids))
        written = create_playlist_from_tracks(name, seeds + track_ids)
        return {
            "name": written.playlist.title,
            "track_count": len(written.tracks),
            "seed_count": len(seeds),
            "recommendation_count": len(written.tracks) - len(seeds),
        }
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
                "artist": r.track.artist,
                "album": r.track.album,
                "year": r.track.year,
                "popularity": r.track.popularity,
                "plex_id": r.track.plex_id,
                "sources": r.sources,
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
    """Run the playlist-populate story line and write to Plex.

    When ``track_ids`` is provided, only that approved selection is appended
    (generation is skipped); otherwise recommendations are generated from the
    playlist's matched tracks. Core's ``populate_playlist`` validates the
    whole selection before any Plex write and reports how many tracks were
    actually added.

    Args:
        playlist_id: Plex rating key of the playlist to populate.
        limit: maximum recommendations to add (generation path only).
        method: ``"average"`` or ``"frequency"`` (generation path only).
        weights: signal weights (generation path only).
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap (generation path only).
        track_ids: approved local track ids to append verbatim.

    Returns:
        A wire-ready dict with the playlist identity, match counts, and how
        many tracks were added.
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
