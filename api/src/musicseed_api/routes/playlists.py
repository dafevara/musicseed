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
from musicseed_api.handlers.recommend import parse_seed_ids

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


@router.get("/playlists")
def list_playlists() -> list[dict]:
    return get_playlists()


@router.post("/playlists/create")
def create_playlist(
    name: Annotated[str, Form()],
    seed_ids: Annotated[str, Form()],
    limit: Annotated[int, Form()] = 50,
    year_min: Annotated[str, Form()] = "",
    year_max: Annotated[str, Form()] = "",
    max_tracks_per_artist: Annotated[int, Form()] = 3,
    w_sonic: Annotated[str, Form()] = "",
    w_popularity: Annotated[str, Form()] = "",
    w_style: Annotated[str, Form()] = "",
    w_genre: Annotated[str, Form()] = "",
    w_era: Annotated[str, Form()] = "",
    w_novelty: Annotated[str, Form()] = "",
) -> dict:
    ids = parse_seed_ids(seed_ids)
    if not ids:
        raise HTTPException(status_code=400, detail="At least one seed track is required.")
    if not name.strip():
        raise HTTPException(status_code=400, detail="Playlist name is required.")

    y_min = int(year_min) if year_min.strip() else None
    y_max = int(year_max) if year_max.strip() else None

    weight_kwargs = {}
    for key, param in [
        ("sonic", w_sonic), ("popularity", w_popularity), ("style", w_style),
        ("genre", w_genre), ("era", w_era), ("novelty", w_novelty),
    ]:
        if param.strip():
            weight_kwargs[key] = float(param)
    weights = Weights(**weight_kwargs) if weight_kwargs else None

    return create_playlist_from_seeds(
        name=name.strip(),
        seed_ids=ids,
        limit=limit,
        weights=weights,
        year_min=y_min,
        year_max=y_max,
        max_tracks_per_artist=max_tracks_per_artist,
    )


@router.get("/playlists/{playlist_id}/preview")
def preview(
    playlist_id: str,
    limit: int = Query(default=10),
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
    limit: Annotated[int, Form()] = 10,
    method: Annotated[str, Form()] = "average",
    year_min: Annotated[str, Form()] = "",
    year_max: Annotated[str, Form()] = "",
    max_tracks_per_artist: Annotated[int, Form()] = 3,
    track_ids: Annotated[str, Form()] = "",
    w_sonic: Annotated[str, Form()] = "",
    w_popularity: Annotated[str, Form()] = "",
    w_style: Annotated[str, Form()] = "",
    w_genre: Annotated[str, Form()] = "",
    w_era: Annotated[str, Form()] = "",
    w_novelty: Annotated[str, Form()] = "",
) -> dict:
    y_min = int(year_min) if year_min.strip() else None
    y_max = int(year_max) if year_max.strip() else None

    selected_ids = parse_seed_ids(track_ids) if track_ids.strip() else None
    if selected_ids is not None and not selected_ids:
        raise HTTPException(status_code=400, detail="No tracks selected to add.")

    weight_kwargs = {}
    for key, param in [
        ("sonic", w_sonic), ("popularity", w_popularity), ("style", w_style),
        ("genre", w_genre), ("era", w_era), ("novelty", w_novelty),
    ]:
        if param.strip():
            weight_kwargs[key] = float(param)
    weights = Weights(**weight_kwargs) if weight_kwargs else None

    return apply_populate(
        playlist_id=playlist_id,
        limit=limit,
        method=_parse_method(method),
        weights=weights,
        year_min=y_min,
        year_max=y_max,
        max_tracks_per_artist=max_tracks_per_artist,
        track_ids=selected_ids,
    )
