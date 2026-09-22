"""Synchronous tool implementations — thin adapters over musicseed core services.

Each function is synchronous, returns JSON-safe data, and lets the core
service's typed exceptions (``NotFoundError``, ``ConfigurationError``,
``PlexAPIError``) propagate so the MCP surface reports them as tool errors.

The preview/apply split is deliberate: preview tools never write to Plex, and
write tools accept only previously-approved local track IDs, which core
validates in full before any Plex write.
"""

from __future__ import annotations

from musicseed.recommender.scoring import RECOMMENDATION_PRESETS, Weights
from musicseed.services import library, playlist_tracks, populate, recommend, typeahead


def _weights(preset: str) -> Weights:
    if preset not in RECOMMENDATION_PRESETS:
        raise ValueError(
            f"Unknown preset '{preset}'. "
            f"Available: {', '.join(sorted(RECOMMENDATION_PRESETS))}"
        )
    return RECOMMENDATION_PRESETS[preset]


def get_status() -> dict:
    """Return library status and enrichment coverage as JSON-safe data."""
    return library.get_status().model_dump(mode="json")


def list_presets() -> dict[str, dict[str, float]]:
    """Return the authoritative named recommendation presets."""
    return {name: weights.model_dump() for name, weights in RECOMMENDATION_PRESETS.items()}


def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """Search the local library by title or artist substring."""
    return [t.model_dump(mode="json") for t in typeahead.search_tracks(query, limit=limit)]


def list_playlists() -> list[dict]:
    """List existing Plex audio playlists with identity and track count."""
    return [
        {"name": p.title, "rating_key": p.rating_key, "track_count": p.leaf_count}
        for p in populate.list_plex_playlists()
    ]


def preview_playlist(
    seed_ids: list[int],
    seed_texts: list[str] | None = None,
    limit: int = 50,
    preset: str = "balanced",
    method: str = "average",
    per_seed_limit: int = 30,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> dict:
    """Preview recommendations for a new playlist without writing to Plex."""
    return recommend.get_recommendations(
        seed_ids=seed_ids,
        seed_texts=seed_texts,
        limit=limit,
        method=method,
        per_seed_limit=per_seed_limit,
        weights=_weights(preset),
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
    ).model_dump(mode="json")


def create_playlist(name: str, seed_ids: list[int], track_ids: list[int]) -> dict:
    """Create a Plex playlist from an approved ordered selection (seeds first).

    Idempotent: retrying with the same name and identical contents returns the
    existing playlist instead of creating a duplicate.
    """
    return playlist_tracks.create_playlist_from_tracks(
        name, [*seed_ids, *track_ids]
    ).model_dump(mode="json")


def preview_populate(
    playlist_id: str,
    limit: int = 10,
    preset: str = "balanced",
    method: str = "average",
    per_seed_limit: int = 30,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> dict:
    """Preview complementary recommendations for an existing Plex playlist."""
    return populate.get_populate_recommendations(
        playlist_id=playlist_id,
        method=method,
        limit=limit,
        per_seed_limit=per_seed_limit,
        weights=_weights(preset),
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
    ).model_dump(mode="json")


def populate_playlist(playlist_id: str, track_ids: list[int]) -> dict:
    """Append approved local track IDs to an existing Plex playlist.

    Idempotent: tracks already present are not re-added and are reported in
    ``already_present_count``.
    """
    return populate.populate_playlist(
        playlist_id=playlist_id, track_ids=track_ids
    ).model_dump(mode="json")
