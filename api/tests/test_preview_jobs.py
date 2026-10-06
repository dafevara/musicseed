"""Background previews return before scoring and publish results separately."""

import threading

import pytest
from fastapi.testclient import TestClient
from musicseed.db.session import get_session, init_db
from musicseed.recommender.scoring import ScoreBreakdown
from musicseed.services import jobs, preview_jobs
from musicseed.services.populate import PopulateResult
from musicseed.services.schemas import ServiceRecommendation, ServiceTrack
from musicseed_api.app import create_app
from musicseed_api.handlers import playlists


@pytest.fixture
def calculation(monkeypatch):
    init_db()
    manager = jobs.JobManager()
    monkeypatch.setattr(jobs, "get_manager", lambda: manager)
    started, release = threading.Event(), threading.Event()
    result = PopulateResult(
        playlist_id="42", playlist_name="Fixture playlist", playlist_track_count=2,
        matched_track_count=2, recommendations=[ServiceRecommendation(
            track=ServiceTrack(id=9, title="Fixture song", artist="Artist", album="Album",
                               year=2000, popularity=50, plex_id=109),
            score=ScoreBreakdown(total=.5, sonic=.5, popularity=.5, style=.5,
                                 genre=.5, era=.5, novelty=.5), sources=["1", "2"],
        )],
    )

    def compute(**options):
        options["on_progress"](50, 100)
        started.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(preview_jobs, "get_populate_recommendations", compute)
    monkeypatch.setattr(playlists, "get_populate_recommendations", lambda **_kw: result)

    def finish():
        release.set()
        with manager._lock:
            threads = [thread for thread, _ in manager._active.values()]
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()

    yield TestClient(create_app()), started, finish
    finish()


def test_start_returns_202_before_scoring_finishes_and_result_matches_sync(calculation):
    client, started, finish = calculation
    endpoint = "/playlists/42/preview-jobs?method=frequency&limit=40&w_sonic=0.3"
    response = client.post(endpoint, data={"request_id": "retry-safe"})
    assert response.status_code == 202
    assert started.wait(5)
    job_id = response.json()["job_id"]
    assert client.post(endpoint, data={"request_id": "retry-safe"}).json() == {"job_id": job_id}
    assert client.post(endpoint, data={"request_id": "other"}).status_code == 409
    status = client.get(f"/jobs/{job_id}").json()
    assert status["state"] == "running"
    assert status["progress_current"] == 50
    assert "result_payload" not in status
    assert "recommendations" not in status
    assert client.get(f"/playlists/preview-jobs/{job_id}/result").status_code == 409
    finish()
    assert client.get(f"/jobs/{job_id}").json()["state"] == "succeeded"
    completed = client.get(f"/playlists/preview-jobs/{job_id}/result")
    assert completed.status_code == 200
    assert completed.json() == client.get(
        "/playlists/42/preview?method=frequency&limit=40&w_sonic=0.3"
    ).json()
    assert client.post(endpoint, data={"request_id": "retry-safe"}).json()["job_id"] == job_id


def test_cancel_does_not_expose_result(calculation):
    client, started, finish = calculation
    response = client.post("/playlists/42/preview-jobs", data={"request_id": "cancel"})
    job_id = response.json()["job_id"]
    assert started.wait(5)
    assert client.post(f"/jobs/{job_id}/cancel").status_code == 200
    assert client.get(f"/jobs/{job_id}").json()["state"] == "cancel_requested"
    finish()
    assert client.get(f"/jobs/{job_id}").json()["state"] == "canceled"
    assert client.get(f"/playlists/preview-jobs/{job_id}/result").status_code == 409


@pytest.mark.parametrize("query", [
    "method=unknown", "limit=0", "limit=999999", "w_sonic=nan", "w_genre=inf",
    "year_min=oops", "year_min=2020&year_max=2000", "max_tracks_per_artist=0",
])
def test_invalid_preview_input_never_submits_job(monkeypatch, query):
    from musicseed_api.routes import playlists as routes

    def unexpected(**_kw):
        pytest.fail("Invalid input must not launch a calculation")

    monkeypatch.setattr(routes, "start_preview_job", unexpected)
    response = TestClient(create_app()).post(
        f"/playlists/42/preview-jobs?{query}", data={"request_id": "invalid"},
    )
    assert response.status_code == 400


def test_poll_reconciles_preview_after_owner_process_dies():
    init_db()
    job_id = jobs.create_job("playlist_preview")
    with get_session() as session:
        session.get(jobs.Job, job_id).pid = None
    client = TestClient(create_app())
    assert client.get(f"/jobs/{job_id}").json()["state"] == "interrupted"
    assert client.get(f"/playlists/preview-jobs/{job_id}/result").status_code == 409
    assert client.get("/playlists/preview-jobs/999999/result").status_code == 404


def test_start_requires_request_identity_and_browser_csrf():
    client = TestClient(create_app())
    assert client.post("/playlists/42/preview-jobs").status_code == 422
    assert client.post("/playlists/42/preview-jobs", data={"request_id": ""}).status_code == 422
    assert client.post("/playlists/42/preview-jobs", data={"request_id": "browser"},
                       headers={"Origin": "http://127.0.0.1:8789"}).status_code == 403
