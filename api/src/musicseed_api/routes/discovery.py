"""JSON endpoints for discovery, setup, and database initialization."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Query
from musicseed.logging_config import get_logger

from musicseed_api.handlers.discovery import (
    apply_config_and_init_db,
    extract_overrides,
    run_discovery,
    run_plex_discovery,
    save_config_overrides,
    wizard_ready,
)

logger = get_logger("api.routes.discovery")


def _log_result(action: str, result) -> None:
    lib = getattr(result, "plex_library_db", None)
    detail = lib.candidates[0].detail if lib is not None and lib.candidates else None
    logger.info(
        "%s: ready=%s missing=%s library_db.ok=%s detail=%s",
        action,
        getattr(result, "ready", None),
        getattr(result, "missing_inputs", None),
        lib.ok if lib is not None else None,
        detail,
    )

router = APIRouter(tags=["discovery"])


@router.get("/discovery/plex-servers")
def get_plex_servers() -> dict:
    servers = run_plex_discovery()
    return {"servers": [s.model_dump() for s in servers]}


@router.get("/discovery")
def get_discovery(
    musicseed_db_path: str = Query(default=""),
    plex_db_path: str = Query(default=""),
    plex_db_ssh: str = Query(default=""),
    plex_url: str = Query(default=""),
    plex_library: str = Query(default=""),
) -> dict:
    result = run_discovery(
        musicseed_db_path=musicseed_db_path,
        plex_db_path=plex_db_path,
        plex_db_ssh=plex_db_ssh,
        plex_url=plex_url,
        plex_library=plex_library,
    )
    return {"ready": wizard_ready(result), "result": result.model_dump()}


@router.post("/discovery/check")
def check_discovery(
    musicseed_db_path: Annotated[str, Form()] = "",
    plex_db_path: Annotated[str, Form()] = "",
    plex_db_ssh: Annotated[str, Form()] = "",
    plex_url: Annotated[str, Form()] = "",
    plex_token: Annotated[str, Form()] = "",
    plex_library: Annotated[str, Form()] = "",
) -> dict:
    overrides, _form = extract_overrides(
        musicseed_db_path=musicseed_db_path,
        plex_db_path=plex_db_path,
        plex_db_ssh=plex_db_ssh,
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
    listenbrainz_token: Annotated[str, Form()] = "",
    plex_url: Annotated[str, Form()] = "",
    plex_token: Annotated[str, Form()] = "",
    plex_library: Annotated[str, Form()] = "",
    plex_db_path: Annotated[str, Form()] = "",
    plex_db_ssh: Annotated[str, Form()] = "",
    plex_db_ssh_password: Annotated[str, Form()] = "",
    plex_db_ssh_port: Annotated[str, Form()] = "",
) -> dict:
    overrides, _form = extract_overrides(
        musicseed_db_path=musicseed_db_path,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        listenbrainz_token=listenbrainz_token,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
        plex_db_path=plex_db_path,
        plex_db_ssh=plex_db_ssh,
        plex_db_ssh_password=plex_db_ssh_password,
        plex_db_ssh_port=plex_db_ssh_port,
    )
    apply_config_and_init_db(**overrides)
    result = run_discovery()
    _log_result("init-db", result)
    return {"ready": wizard_ready(result), "result": result.model_dump()}


@router.post("/discovery/config")
def save_config(
    musicseed_db_path: Annotated[str, Form()] = "",
    spotify_client_id: Annotated[str, Form()] = "",
    spotify_client_secret: Annotated[str, Form()] = "",
    listenbrainz_token: Annotated[str, Form()] = "",
    plex_url: Annotated[str, Form()] = "",
    plex_token: Annotated[str, Form()] = "",
    plex_library: Annotated[str, Form()] = "",
    plex_db_path: Annotated[str, Form()] = "",
    plex_db_ssh: Annotated[str, Form()] = "",
    plex_db_ssh_password: Annotated[str, Form()] = "",
    plex_db_ssh_port: Annotated[str, Form()] = "",
) -> dict:
    overrides, _form = extract_overrides(
        musicseed_db_path=musicseed_db_path,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        listenbrainz_token=listenbrainz_token,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
        plex_db_path=plex_db_path,
        plex_db_ssh=plex_db_ssh,
        plex_db_ssh_password=plex_db_ssh_password,
        plex_db_ssh_port=plex_db_ssh_port,
    )
    save_config_overrides(**overrides)
    result = run_discovery()
    _log_result("config saved", result)
    return {"ready": wizard_ready(result), "result": result.model_dump()}
