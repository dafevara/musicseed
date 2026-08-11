"""Recommendation screen — seed selection, filters, and scored results.

Thin surface: routes delegate to ``musicseed_api.handlers.recommend`` for
seed parsing, typeahead, and recommendation execution. No scoring, candidate
generation, or Plex access lives here.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from musicseed.exceptions import NotFoundError
from musicseed_api.handlers.recommend import (
    load_seed_tracks,
    parse_seed_ids,
    run_recommendations,
    typeahead_search,
)

from musicseed_web.render import templates

router = APIRouter()


@router.get("/recommend", response_class=HTMLResponse)
def recommend_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "recommend.html", {"seeds": [], "seed_ids": "", "error": None}
    )


@router.get("/recommend/typeahead", response_class=HTMLResponse)
def typeahead(
    request: Request,
    q: str = Query(default="", min_length=1),
    seed_ids: str = Query(default=""),
) -> HTMLResponse:
    exclude_ids = parse_seed_ids(seed_ids)
    tracks = typeahead_search(q, exclude_ids)
    return templates.TemplateResponse(
        request, "_recommend_typeahead.html", {"tracks": tracks, "seed_ids": seed_ids}
    )


@router.post("/recommend/seeds", response_class=HTMLResponse)
def seeds(
    request: Request,
    action: Annotated[str, Form()] = "",
    track_id: Annotated[int, Form()] = 0,
    seed_ids: Annotated[str, Form()] = "",
) -> HTMLResponse:
    ids = parse_seed_ids(seed_ids)

    if action == "add" and track_id and track_id not in ids:
        ids.append(track_id)
    elif action == "remove":
        ids = [i for i in ids if i != track_id]

    seed_ids_str = ",".join(str(i) for i in ids)
    seeds_list = load_seed_tracks(ids)

    resp = templates.TemplateResponse(
        request,
        "_recommend_seeds.html",
        {"seeds": seeds_list, "seed_ids": seed_ids_str},
    )
    resp.headers["HX-Trigger"] = "seedsChanged"
    return resp


@router.post("/recommend/results", response_class=HTMLResponse)
def results(
    request: Request,
    seed_ids: Annotated[str, Form()] = "",
    limit: Annotated[int, Form()] = 50,
    year_min: Annotated[str, Form()] = "",
    year_max: Annotated[str, Form()] = "",
    max_tracks_per_artist: Annotated[int, Form()] = 3,
    min_score: Annotated[str, Form()] = "",
) -> HTMLResponse:
    ids = parse_seed_ids(seed_ids)

    if not ids:
        return templates.TemplateResponse(
            request,
            "_recommend_results.html",
            {"seeds": [], "recommendations": [], "error": None, "empty": True},
        )

    y_min = int(year_min) if year_min.strip() else None
    y_max = int(year_max) if year_max.strip() else None
    ms = float(min_score) if min_score.strip() else None

    seeds_list = load_seed_tracks(ids)

    try:
        result = run_recommendations(
            seed_ids=ids,
            limit=limit,
            year_min=y_min,
            year_max=y_max,
            max_tracks_per_artist=max_tracks_per_artist,
            min_score=ms,
        )
    except (NotFoundError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "_recommend_results.html",
            {
                "seeds": seeds_list,
                "recommendations": [],
                "error": str(exc),
                "empty": False,
            },
        )

    return templates.TemplateResponse(
        request,
        "_recommend_results.html",
        {
            "seeds": result.seed_tracks,
            "recommendations": result.recommendations,
            "error": None,
            "empty": not result.recommendations,
        },
    )
