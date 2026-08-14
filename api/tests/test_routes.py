"""Route smoke tests — every route module has at least one offline test.

Services and handlers are stubbed at the boundary so the suite runs with no
Plex server and no real database.
"""

import musicseed_api.routes.dashboard as dashboard_routes
import musicseed_api.routes.discovery as discovery_routes
import musicseed_api.routes.enrichment as enrichment_routes
import musicseed_api.routes.library as library_routes
import musicseed_api.routes.playlists as playlists_routes
import musicseed_api.routes.recommend as recommend_routes
import musicseed_api.routes.sonic as sonic_routes
from fastapi.testclient import TestClient
from musicseed.recommender.scoring import ScoreBreakdown, SonicCoverage, Weights
from musicseed.services.library import EnrichmentCoverage, LibraryStatus
from musicseed.services.plex_discovery import DiscoveredPlexServer
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
    # The response carries the effective weights so the UI can render
    # weighted contributions.
    assert body["weights"]["sonic"] == 0.30


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


def test_recommend_presets_match_core():
    from musicseed.recommender.scoring import RECOMMENDATION_PRESETS

    resp = TestClient(create_app()).get("/recommend/presets")
    assert resp.status_code == 200
    expected = {name: w.model_dump() for name, w in RECOMMENDATION_PRESETS.items()}
    assert resp.json() == expected


def test_populate_route_passes_selected_track_ids(monkeypatch):
    captured = {}

    def fake_apply_populate(**kwargs):
        captured.update(kwargs)
        return {
            "playlist_id": kwargs["playlist_id"],
            "playlist_name": "Test",
            "playlist_track_count": 5,
            "matched_track_count": 3,
            "added_count": 2,
        }

    monkeypatch.setattr(playlists_routes, "apply_populate", fake_apply_populate)
    resp = TestClient(create_app()).post(
        "/playlists/99/populate", data={"track_ids": "10,20,30"}
    )
    assert resp.status_code == 200
    assert captured["playlist_id"] == "99"
    assert captured["track_ids"] == [10, 20, 30]


def test_preview_route_passes_weights(monkeypatch):
    captured = {}

    def fake_preview_populate(**kwargs):
        captured.update(kwargs)
        return {
            "playlist_id": kwargs["playlist_id"],
            "playlist_name": "Test",
            "playlist_track_count": 5,
            "matched_track_count": 3,
            "weights": (kwargs["weights"] or Weights()).model_dump(),
            "recommendations": [],
        }

    monkeypatch.setattr(playlists_routes, "preview_populate", fake_preview_populate)
    resp = TestClient(create_app()).get(
        "/playlists/99/preview",
        params={"limit": "10", "w_sonic": "0.5", "w_popularity": "0.2"},
    )
    assert resp.status_code == 200
    assert captured["playlist_id"] == "99"
    assert captured["method"] == "average"
    assert captured["weights"].sonic == 0.5
    assert captured["weights"].popularity == 0.2


def test_preview_route_passes_frequency_method(monkeypatch):
    captured = {}

    def fake_preview_populate(**kwargs):
        captured.update(kwargs)
        return {
            "playlist_id": kwargs["playlist_id"],
            "playlist_name": "Test",
            "method": kwargs["method"],
            "recommendations": [],
        }

    monkeypatch.setattr(playlists_routes, "preview_populate", fake_preview_populate)
    resp = TestClient(create_app()).get(
        "/playlists/99/preview",
        params={"method": "frequency"},
    )
    assert resp.status_code == 200
    assert captured["method"] == "frequency"


def test_preview_route_rejects_unknown_method():
    resp = TestClient(create_app()).get(
        "/playlists/99/preview",
        params={"method": "mood"},
    )
    assert resp.status_code == 400


def test_plex_servers_route(monkeypatch):
    servers = [
        DiscoveredPlexServer(
            name="Living Room", host="192.168.1.5", port=32400,
            version="1.41.0.9000", machine_identifier="abc",
        )
    ]
    monkeypatch.setattr(discovery_routes, "run_plex_discovery", lambda: servers)
    resp = TestClient(create_app()).get("/discovery/plex-servers")
    assert resp.status_code == 200
    body = resp.json()["servers"]
    assert body[0]["name"] == "Living Room"
    assert body[0]["host"] == "192.168.1.5"
    assert body[0]["port"] == 32400


def test_save_config_route_persists_without_init(monkeypatch):
    captured = {}

    def fake_save_config_overrides(**kwargs):
        captured.update(kwargs)

    class FakeResult:
        def model_dump(self):
            return {"ok": True}

    monkeypatch.setattr(discovery_routes, "save_config_overrides", fake_save_config_overrides)
    monkeypatch.setattr(discovery_routes, "run_discovery", lambda: FakeResult())
    monkeypatch.setattr(discovery_routes, "wizard_ready", lambda result: False)
    resp = TestClient(create_app()).post(
        "/discovery/config",
        data={
            "plex_url": "http://plex.local:32400",
            "plex_token": "tok",
            "spotify_client_id": "cid",
        },
    )
    assert resp.status_code == 200
    assert captured["plex_url"] == "http://plex.local:32400"
    assert captured["plex_token"] == "tok"
    assert captured["spotify_client_id"] == "cid"
