"""JSON endpoints for enrichment and credential management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form

from musicseed_api.handlers.enrichment import ENRICH_KIND, run_enrich_job, save_spotify_creds
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
    job_id = submit_job(ENRICH_KIND, run_enrich_job)
    return {"job_id": job_id}


@router.post("/enrichment/listenbrainz")
def start_listenbrainz_enrich() -> dict:
    job_id = submit_job(ENRICH_KIND, run_enrich_job, "listenbrainz")
    return {"job_id": job_id}
