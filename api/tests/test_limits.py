"""Resource limits: bounded request sizes, seeds, selections, and results."""

from fastapi.testclient import TestClient
from musicseed_api.app import create_app

client = TestClient(create_app())


def test_recommend_rejects_too_many_seeds():
    seeds = ",".join(str(i) for i in range(1, 60))
    resp = client.post("/recommend", data={"seed_ids": seeds})
    assert resp.status_code == 400
    assert "Too many seed tracks" in resp.json()["detail"]


def test_recommend_rejects_excessive_limit():
    resp = client.post("/recommend", data={"seed_ids": "1", "limit": "999999"})
    assert resp.status_code == 400
    assert "limit must be between" in resp.json()["detail"]


def test_playlist_selection_rejects_oversized_selection():
    ids = ",".join(str(i) for i in range(1, 600))
    resp = client.post(
        "/playlists/create",
        data={"name": "x", "seed_ids": "1", "track_ids": ids},
    )
    assert resp.status_code == 400
    assert "exceeds the maximum" in resp.json()["detail"]


def test_request_body_size_is_bounded():
    big = b"x" * (1_048_576 + 1)
    resp = client.post("/recommend", content=big, headers={"Content-Type": "text/plain"})
    assert resp.status_code == 413


def test_typeahead_query_length_is_bounded():
    resp = client.get("/recommend/typeahead", params={"q": "x" * 500})
    assert resp.status_code == 422  # FastAPI validates the max_length constraint
