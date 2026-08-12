"""JSON endpoints for Plex playlists."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query
from musicseed.exceptions import ConfigurationError, NotFoundError
from musicseed.recommender.scoring import Weights

from musicseed_api.handlers.playlists import (
    apply_populate,
    create_playlist_from_seeds,
    get_playlists,
    preview_populate,
)
from musicseed_api.handlers.recommend import parse_seed_ids

router = APIRouter(tags=["playlists"])


@router.get("/playlists")
def list_playlists() -> list[dict]:
    try:
        return get_playlists()
    except ConfigurationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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

    try:
        return create_playlist_from_seeds(
            name=name.strip(),
            seed_ids=ids,
            limit=limit,
            weights=weights,
            year_min=y_min,
            year_max=y_max,
            max_tracks_per_artist=max_tracks_per_artist,
        )
    except ConfigurationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/playlists/{name}/preview")
def preview(
    name: str,
    limit: int = Query(default=10),
    year_min: str | None = Query(default=None),
    year_max: str | None = Query(default=None),
    max_tracks_per_artist: int = Query(default=3),
) -> dict:
    y_min = int(year_min) if year_min else None
    y_max = int(year_max) if year_max else None
    try:
        return preview_populate(
            playlist_name=name,
            limit=limit,
            year_min=y_min,
            year_max=y_max,
            max_tracks_per_artist=max_tracks_per_artist,
        )
    except ConfigurationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/playlists/{name}/populate")
def populate(
    name: str,
    limit: Annotated[int, Form()] = 10,
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

    try:
        return apply_populate(
            playlist_name=name,
            limit=limit,
            weights=weights,
            year_min=y_min,
            year_max=y_max,
            max_tracks_per_artist=max_tracks_per_artist,
        )
    except ConfigurationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
