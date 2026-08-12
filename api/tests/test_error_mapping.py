"""Central error contract: typed core exceptions map to HTTP status codes."""

import musicseed_api.routes.library as library_routes
import musicseed_api.routes.recommend as recommend_routes
from fastapi.testclient import TestClient
from musicseed.exceptions import JobConflictError, NotFoundError
from musicseed_api.app import create_app


def test_missing_job_maps_to_404():
    client = TestClient(create_app())
    resp = client.get("/jobs/999999")
    assert resp.status_code == 404
    assert "999999" in resp.json()["detail"]


def test_missing_seed_maps_to_404(monkeypatch):
    def boom(**kwargs):
        raise NotFoundError("No seed track found with id=12345")

    monkeypatch.setattr(recommend_routes, "run_recommendations", boom)
    client = TestClient(create_app())
    resp = client.post("/recommend", data={"seed_ids": "12345"})
    assert resp.status_code == 404
    assert "No seed track" in resp.json()["detail"]


def test_duplicate_job_maps_to_409(monkeypatch):
    def boom(kind, target, *args, **kwargs):
        raise JobConflictError("A import job is already running — wait for it to finish.")

    monkeypatch.setattr(library_routes, "submit_job", boom)
    client = TestClient(create_app())
    resp = client.post("/library/import")
    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"]
