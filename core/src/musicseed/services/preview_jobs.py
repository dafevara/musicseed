"""Background playlist previews with persisted results and cooperative cancellation."""

from __future__ import annotations

import hashlib
import json
import time

from musicseed.clients.plex import PlexAPIError
from musicseed.exceptions import CalculationCanceledError, ConfigurationError, NotFoundError
from musicseed.recommender.populate import PopulateMethod
from musicseed.recommender.scoring import Weights
from musicseed.services import jobs
from musicseed.services.populate import PopulateResult, get_populate_recommendations


class PreviewResult(PopulateResult):
    """A persisted preview with the strategy and weights used to calculate it."""

    method: PopulateMethod
    weights: Weights


def start_preview(
    playlist_id: str, *, request_id: str, method: PopulateMethod = "average",
    limit: int = 40, weights: Weights | None = None, year_min: int | None = None,
    year_max: int | None = None, max_tracks_per_artist: int = 3,
) -> int:
    """Submit a preview; retries with the same ID and inputs reuse its job."""
    weights = weights or Weights()
    inputs = dict(
        playlist_id=playlist_id, method=method, limit=limit, weights=weights.model_dump(),
        year_min=year_min, year_max=year_max, max_tracks_per_artist=max_tracks_per_artist,
    )
    key = hashlib.sha256(json.dumps([request_id, inputs], sort_keys=True).encode()).hexdigest()
    return jobs.get_manager().submit(
        jobs.JobKind.PLAYLIST_PREVIEW, _run_preview,
        request_key=key, **{**inputs, "weights": weights},
    )


def get_preview_result(job_id: int) -> PreviewResult:
    """Return a completed preview without including its payload in progress polling."""
    return PreviewResult.model_validate(
        jobs.get_job_result(job_id, jobs.JobKind.PLAYLIST_PREVIEW),
    )


def _run_preview(job_id: int, *, weights: Weights, **inputs) -> None:
    jobs.update_progress(job_id, 0, checkpoint="Reading playlist and preparing recommendations…")
    last_update = 0.0

    def should_cancel() -> bool:
        job = jobs.get_job(job_id)
        return job is None or job["state"] == jobs.JobState.CANCEL_REQUESTED

    def on_progress(current: int, total: int) -> None:
        nonlocal last_update
        now = time.monotonic()
        if now - last_update >= 0.5 or current == total:
            jobs.update_progress(job_id, current, total, "Checking your library…")
            last_update = now

    try:
        if should_cancel():
            raise CalculationCanceledError("Calculation canceled.")
        result = get_populate_recommendations(
            weights=weights, on_progress=on_progress, should_cancel=should_cancel, **inputs,
        )
        if should_cancel():
            raise CalculationCanceledError("Calculation canceled.")
        jobs.update_progress(job_id, 1, 1, "Recommendations ready")
        jobs.complete_job(
            job_id, json.dumps({"recommendation_count": len(result.recommendations)}),
            result_payload=PreviewResult(
                **result.model_dump(), method=inputs["method"], weights=weights,
            ).model_dump(mode="json"),
        )
    except CalculationCanceledError:
        jobs.cancel_job(job_id)
    except (ConfigurationError, NotFoundError, PlexAPIError) as error:
        jobs.fail_job(job_id, str(error))
    except Exception as error:
        jobs.fail_job(job_id, f"Calculation failed ({type(error).__name__}). Please try again.")
