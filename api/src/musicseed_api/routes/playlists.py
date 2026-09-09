"""JSON endpoints for Plex playlists."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query
from musicseed.recommender.populate import PopulateMethod
from musicseed.recommender.scoring import Weights

from musicseed_api.handlers.playlists import (
    apply_populate,
    create_playlist_from_seeds,
    get_playlists,
    preview_populate,
)

router = APIRouter(tags=["playlists"])

_METHODS = {"average", "frequency"}


def _parse_method(value: str) -> PopulateMethod:
    method = value.strip().lower() or "average"
    if method not in _METHODS:
        raise HTTPException(
            status_code=400,
            detail="method must be 'average' or 'frequency'.",
        )
    return method  # type: ignore[return-value]


def _approved_ids(value: str) -> list[int]:
    """Reject empty/malformed selections instead of generating or writing a subset."""
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(
        len(part) > 19 or not part.isascii() or not part.isdecimal() for part in parts
    ):
        raise HTTPException(status_code=400, detail="Provide approved track_ids from a preview.")
    ids = [int(part) for part in parts]
    if any(not 0 < track_id <= 2**63 - 1 for track_id in ids):
        raise HTTPException(status_code=400, detail="Track IDs must be positive SQLite integers.")
    return list(dict.fromkeys(ids))


@router.get("/playlists")
def list_playlists() -> list[dict]:
    return get_playlists()


@router.post("/playlists/create")
def create_playlist(
    name: Annotated[str, Form()],
    seed_ids: Annotated[str, Form()],
    track_ids: Annotated[str, Form()],
) -> dict:
    """Create the approved preview; scoring inputs belong to the preview request."""
    ids = _approved_ids(seed_ids)
    selected_ids = _approved_ids(track_ids)
    if not name.strip():
        raise HTTPException(status_code=400, detail="Playlist name is required.")
    return create_playlist_from_seeds(
        name=name.strip(), seed_ids=ids, track_ids=selected_ids,
    )


@router.get("/playlists/{playlist_id}/preview")
def preview(
    playlist_id: str,
    limit: int = Query(default=40),
    method: str = Query(default="average"),
    year_min: str | None = Query(default=None),
    year_max: str | None = Query(default=None),
    max_tracks_per_artist: int = Query(default=3),
    w_sonic: str = Query(default=""),
    w_popularity: str = Query(default=""),
    w_style: str = Query(default=""),
    w_genre: str = Query(default=""),
    w_era: str = Query(default=""),
    w_novelty: str = Query(default=""),
) -> dict:
    y_min = int(year_min) if year_min else None
    y_max = int(year_max) if year_max else None

    weight_kwargs = {}
    for key, param in [
        ("sonic", w_sonic), ("popularity", w_popularity), ("style", w_style),
        ("genre", w_genre), ("era", w_era), ("novelty", w_novelty),
    ]:
        if param.strip():
            weight_kwargs[key] = float(param)
    weights = Weights(**weight_kwargs) if weight_kwargs else None

    return preview_populate(
        playlist_id=playlist_id,
        limit=limit,
        method=_parse_method(method),
        weights=weights,
        year_min=y_min,
        year_max=y_max,
        max_tracks_per_artist=max_tracks_per_artist,
    )


@router.post("/playlists/{playlist_id}/populate")
def populate(
    playlist_id: str,
    track_ids: Annotated[str, Form()],
) -> dict:
    """Append the approved selection without regenerating or re-filtering it."""
    return apply_populate(playlist_id=playlist_id, track_ids=_approved_ids(track_ids))
