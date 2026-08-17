"""JSON endpoints for enrichment and credential management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form

from musicseed_api.handlers.enrichment import (
    enrich_kind,
    run_enrich_job,
    save_listenbrainz_token,
    save_spotify_creds,
)
from musicseed_api.handlers.jobs import submit_job

router = APIRouter(tags=["enrichment"])


@router.post("/enrichment/spotify")
def start_spotify_enrich(
    spotify_client_id: Annotated[str, Form()] = "",
    spotify_client_secret: Annotated[str, Form()] = "",
) -> dict:
    save_spotify_creds(
        spotify_client_id.strip(), spotify_client_secret.strip(),
    )
    job_id = submit_job(enrich_kind("spotify"), run_enrich_job)
    return {"job_id": job_id}


@router.post("/enrichment/listenbrainz")
def start_listenbrainz_enrich(
    listenbrainz_token: Annotated[str, Form()] = "",
) -> dict:
    save_listenbrainz_token(listenbrainz_token.strip())
    job_id = submit_job(enrich_kind("listenbrainz"), run_enrich_job, "listenbrainz")
    return {"job_id": job_id}
