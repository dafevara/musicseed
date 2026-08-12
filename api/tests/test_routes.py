"""Route smoke tests — every route module has at least one offline test.

Services and handlers are stubbed at the boundary so the suite runs with no
Plex server and no real database.
"""

import musicseed_api.routes.dashboard as dashboard_routes
import musicseed_api.routes.enrichment as enrichment_routes
import musicseed_api.routes.library as library_routes
import musicseed_api.routes.recommend as recommend_routes
import musicseed_api.routes.sonic as sonic_routes
from fastapi.testclient import TestClient
from musicseed.recommender.scoring import ScoreBreakdown, SonicCoverage
from musicseed.services.library import EnrichmentCoverage, LibraryStatus
from musicseed_api.app import create_app
from pydantic import BaseModel


def test_library_status_route(monkeypatch):
    status = LibraryStatus(
        db_path="x", db_size_bytes=1, plex_url="u", plex_db="d", plex_library="l",
        artist_count=1, album_count=1, track_count=5, play_count=0,
        genre_count=0, mood_count=0, style_count=0,
        enrichment=EnrichmentCoverage(
            tracks_with_mbid=0, tracks_with_spotify=0, tracks_with_listenbrainz=0,
            tracks_with_sonic=0, spotify_attempted=0, listenbrainz_attempted=0,
        ),
    )
    monkeypatch.setattr(library_routes, "get_library_status", lambda: status)
    resp = TestClient(create_app()).get("/library/status")
    assert resp.status_code == 200
    assert resp.json()["track_count"] == 5


def test_library_import_route(monkeypatch):
    monkeypatch.setattr(library_routes, "submit_job", lambda kind, target: 123)
    resp = TestClient(create_app()).post("/library/import")
    assert resp.json() == {"job_id": 123}


def test_enrichment_spotify_route(monkeypatch):
    monkeypatch.setattr(enrichment_routes, "submit_job", lambda kind, target: 123)
    resp = TestClient(create_app()).post("/enrichment/spotify", data={})
    assert resp.json() == {"job_id": 123}


def test_recommend_typeahead_route(monkeypatch):
    monkeypatch.setattr(recommend_routes, "typeahead_search", lambda q, exclude: [])
    resp = TestClient(create_app()).get("/recommend/typeahead", params={"q": "ab"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_recommend_route(monkeypatch):
    class FakeTrack:
        id = 1
        title = "t"
        artist = None

    class FakeRec:
        track = FakeTrack()
        score = ScoreBreakdown(
            total=0.5, sonic=0.5, popularity=0.5,
            style=0.5, genre=0.5, era=0.5, novelty=0.5,
        )

    class FakeResult:
        seed_tracks = [FakeTrack()]
        recommendations = [FakeRec()]
        sonic_coverage = SonicCoverage(candidates=1, with_vector=0)

    monkeypatch.setattr(recommend_routes, "run_recommendations", lambda **kw: FakeResult())
    resp = TestClient(create_app()).post("/recommend", data={"seed_ids": "1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["seed_track_ids"] == [1]
    assert body["recommendations"][0]["track_id"] == 1
    assert body["sonic_coverage"]["with_vector"] == 0


def test_sonic_status_route(monkeypatch):
    class Fake(BaseModel):
        total_tracks: int = 0
        analyzed_tracks: int = 0
        unanalyzed_albums: list = []

    monkeypatch.setattr(sonic_routes, "get_sonic_coverage", lambda *a, **k: Fake())
    resp = TestClient(create_app()).get("/sonic/status")
    assert resp.status_code == 200
    assert resp.json()["total_tracks"] == 0


def test_dashboard_route(monkeypatch):
    class Fake(BaseModel):
        ok: bool = True

    monkeypatch.setattr(dashboard_routes, "get_dashboard_snapshot", lambda **k: Fake())
    resp = TestClient(create_app()).get("/dashboard")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
