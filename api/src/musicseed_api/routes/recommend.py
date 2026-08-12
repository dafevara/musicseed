"""JSON endpoints for recommendations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Query
from musicseed.recommender.scoring import Weights

from musicseed_api.handlers.recommend import (
    get_recommendation_presets,
    parse_seed_ids,
    run_recommendations,
    typeahead_search,
)

router = APIRouter(tags=["recommend"])


@router.get("/recommend/presets")
def presets() -> dict[str, dict[str, float]]:
    return get_recommendation_presets()


@router.get("/recommend/typeahead")
def typeahead(
    q: str = Query(default="", min_length=1),
    exclude: str = Query(default=""),
) -> list[dict]:
    exclude_ids = parse_seed_ids(exclude)
    tracks = typeahead_search(q, exclude_ids)
    return [
        {
            "id": t.id,
            "title": t.title,
            "artist": t.artist.name if t.artist else None,
            "album": t.album.title if t.album else None,
            "year": t.year,
        }
        for t in tracks
    ]


@router.post("/recommend")
def recommend(
    seed_ids: Annotated[str, Form()],
    limit: Annotated[int, Form()] = 50,
    year_min: Annotated[str, Form()] = "",
    year_max: Annotated[str, Form()] = "",
    max_tracks_per_artist: Annotated[int, Form()] = 3,
    min_score: Annotated[str, Form()] = "",
    w_sonic: Annotated[str, Form()] = "",
    w_popularity: Annotated[str, Form()] = "",
    w_style: Annotated[str, Form()] = "",
    w_genre: Annotated[str, Form()] = "",
    w_era: Annotated[str, Form()] = "",
    w_novelty: Annotated[str, Form()] = "",
) -> dict:
    ids = parse_seed_ids(seed_ids)
    y_min = int(year_min) if year_min.strip() else None
    y_max = int(year_max) if year_max.strip() else None
    ms = float(min_score) if min_score.strip() else None

    weight_kwargs = {}
    for key, param in [
        ("sonic", w_sonic), ("popularity", w_popularity), ("style", w_style),
        ("genre", w_genre), ("era", w_era), ("novelty", w_novelty),
    ]:
        if param.strip():
            weight_kwargs[key] = float(param)

    weights = Weights(**weight_kwargs) if weight_kwargs else None

    result = run_recommendations(
        seed_ids=ids,
        limit=limit,
        year_min=y_min,
        year_max=y_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=ms,
        weights=weights,
    )
    return {
        "seed_track_ids": [t.id for t in result.seed_tracks],
        "recommendations": [
            {
                "track_id": r.track.id,
                "title": r.track.title,
                "artist": r.track.artist.name if r.track.artist else None,
                "score": r.score,
            }
            for r in result.recommendations
        ],
        "sonic_coverage": result.sonic_coverage.model_dump(),
    }
