"""JSON endpoints for Plex playlists."""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query
from musicseed.config import get_config
from musicseed.recommender.populate import PopulateMethod
from musicseed.recommender.scoring import Weights

from musicseed_api.handlers.playlists import (
    apply_populate,
    create_playlist_from_seeds,
    get_playlists,
    get_preview_job_result,
    preview_populate,
    start_preview_job,
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
    """Reject empty/malformed/oversized selections instead of writing a subset."""
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(
        len(part) > 19 or not part.isascii() or not part.isdecimal() for part in parts
    ):
        raise HTTPException(status_code=400, detail="Provide approved track_ids from a preview.")
    ids = [int(part) for part in parts]
    if any(not 0 < track_id <= 2**63 - 1 for track_id in ids):
        raise HTTPException(status_code=400, detail="Track IDs must be positive SQLite integers.")
    limit = get_config().limits.max_selection_tracks
    if len(ids) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"Selection exceeds the maximum of {limit} tracks.",
        )
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
    if len(ids) > get_config().limits.max_seeds:
        raise HTTPException(
            status_code=400,
            detail=f"Too many seed tracks (max {get_config().limits.max_seeds}).",
        )
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
    """Preview complementary recommendations for an existing playlist."""
    return preview_populate(playlist_id=playlist_id, **_preview_options(
        limit, method, year_min, year_max, max_tracks_per_artist,
        dict(sonic=w_sonic, popularity=w_popularity, style=w_style,
             genre=w_genre, era=w_era, novelty=w_novelty),
    ))


@router.post("/playlists/{playlist_id}/preview-jobs", status_code=202)
def start_preview(
    playlist_id: str,
    request_id: Annotated[str, Form(min_length=1, max_length=128)],
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
    """Start a calculation and return immediately; poll /jobs/{job_id}."""
    return start_preview_job(playlist_id=playlist_id, request_id=request_id, **_preview_options(
        limit, method, year_min, year_max, max_tracks_per_artist,
        dict(sonic=w_sonic, popularity=w_popularity, style=w_style,
             genre=w_genre, era=w_era, novelty=w_novelty),
    ))


@router.get("/playlists/preview-jobs/{job_id}/result")
def preview_result(job_id: int) -> dict:
    """Fetch the completed preview once the job has succeeded."""
    return get_preview_job_result(job_id)


def _preview_options(limit, method, year_min, year_max, max_tracks_per_artist, weight_params):
    maximum = get_config().limits.max_recommendations
    if not 0 < limit <= maximum:
        raise HTTPException(status_code=400, detail=f"limit must be between 1 and {maximum}.")
    if max_tracks_per_artist <= 0:
        raise HTTPException(status_code=400, detail="Artist cap must be positive.")
    try:
        y_min = int(year_min) if year_min else None
        y_max = int(year_max) if year_max else None
        weight_kwargs = {key: float(value) for key, value in weight_params.items() if value.strip()}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid year or weight.") from None
    if any(not math.isfinite(value) for value in weight_kwargs.values()):
        raise HTTPException(status_code=400, detail="Weights must be finite numbers.")
    if y_min is not None and y_max is not None and y_min > y_max:
        raise HTTPException(status_code=400, detail="Minimum year exceeds maximum year.")
    return dict(
        limit=limit, method=_parse_method(method),
        weights=Weights(**weight_kwargs) if weight_kwargs else None,
        year_min=y_min, year_max=y_max, max_tracks_per_artist=max_tracks_per_artist,
    )


@router.post("/playlists/{playlist_id}/populate")
def populate(
    playlist_id: str,
    track_ids: Annotated[str, Form()],
) -> dict:
    """Append the approved selection without regenerating or re-filtering it."""
    return apply_populate(playlist_id=playlist_id, track_ids=_approved_ids(track_ids))
