"""JSON endpoints for discovery, setup, and database initialization."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Query

from musicseed_api.handlers.discovery import (
    apply_config_and_init_db,
    extract_overrides,
    run_discovery,
    wizard_ready,
)

router = APIRouter(tags=["discovery"])


@router.get("/discovery")
def get_discovery(
    musicseed_db_path: str = Query(default=""),
    plex_db_path: str = Query(default=""),
    plex_url: str = Query(default=""),
    plex_token: str = Query(default=""),
    plex_library: str = Query(default=""),
) -> dict:
    result = run_discovery(
        musicseed_db_path=musicseed_db_path,
        plex_db_path=plex_db_path,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
    )
    return {"ready": wizard_ready(result), "result": result.model_dump()}


@router.post("/discovery/check")
def check_discovery(
    musicseed_db_path: Annotated[str, Form()] = "",
    plex_db_path: Annotated[str, Form()] = "",
    plex_url: Annotated[str, Form()] = "",
    plex_token: Annotated[str, Form()] = "",
    plex_library: Annotated[str, Form()] = "",
) -> dict:
    overrides, _form = extract_overrides(
        musicseed_db_path=musicseed_db_path,
        plex_db_path=plex_db_path,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
    )
    result = run_discovery(**overrides)
    return {"ready": wizard_ready(result), "result": result.model_dump()}


@router.post("/discovery/init-db")
def init_database(
    musicseed_db_path: Annotated[str, Form()] = "",
    spotify_client_id: Annotated[str, Form()] = "",
    spotify_client_secret: Annotated[str, Form()] = "",
    plex_url: Annotated[str, Form()] = "",
    plex_token: Annotated[str, Form()] = "",
    plex_library: Annotated[str, Form()] = "",
    plex_db_path: Annotated[str, Form()] = "",
) -> dict:
    overrides, _form = extract_overrides(
        musicseed_db_path=musicseed_db_path,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
        plex_db_path=plex_db_path,
    )
    apply_config_and_init_db(**overrides)
    result = run_discovery()
    return {"ready": wizard_ready(result), "result": result.model_dump()}
