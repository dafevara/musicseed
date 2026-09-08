"""Offline API workflows with real SQLite services/DTOs, not fake ORM-shaped objects."""

import pytest
from fastapi.testclient import TestClient
from musicseed.clients.plex import MediaItem, Playlist
from musicseed.config import get_config
from musicseed.context import get_context
from musicseed.db.models import Album, Artist, Track, TrackVector
from musicseed.db.session import init_db
from musicseed.services import playlist_tracks, populate, recommend
from musicseed_api.app import create_app


@pytest.fixture
def workflow(monkeypatch):
    get_config().plex.token = "fixture-token"
    ctx = get_context()
    init_db(ctx)
    with ctx.session() as session:
        session.add_all([
            Track(id=1, title="Seed", plex_id=101, artist=Artist(name="Seed Artist")),
            Track(id=2, title="Sparse seed", plex_id=102, artist=Artist(name="Other Artist")),
            Track(id=3, title="Candidate", plex_id=103, artist=Artist(name="Real Artist"),
                  album=Album(title="Real Album"), year=2001, popularity_score=0.7),
            TrackVector(plex_id=101, vector=[1.0] * 50),
            TrackVector(plex_id=103, vector=[1.0] * 50),
        ])

    class FakePlex:
        created = []
        added = []

        def get_playlist(self, playlist_id):
            return Playlist(rating_key=playlist_id, title="Fixture", leaf_count=2)

        def get_playlist_tracks(self, _playlist_id):
            return [MediaItem(rating_key="101"), MediaItem(rating_key="102")]

        def create_playlist(self, name, ids):
            self.created.append(list(ids))
            return Playlist(rating_key="new", title=name, leaf_count=len(ids))

        def add_to_playlist(self, playlist_id, ids):
            self.added.append((playlist_id, list(ids)))

    plex = FakePlex()
    monkeypatch.setattr(populate, "_plex_client", lambda _ctx=None: plex)
    monkeypatch.setattr(playlist_tracks, "PlexClient", lambda **_kw: plex)
    yield TestClient(create_app()), ctx, plex
    ctx.engine.dispose()


def test_recommend_and_populate_api_preserve_real_dto_fields_and_evidence(workflow):
    client, ctx, _plex = workflow
    normal = client.post("/recommend", data={"seed_ids": "1,2"})
    assert normal.status_code == 200
    responses = [normal]
    for method in ("average", "frequency"):
        response = client.get("/playlists/fixture/preview", params={"method": method})
        assert response.status_code == 200
        responses.append(response)
    ctx.engine.dispose()
    for response in responses:
        item = response.json()["recommendations"][0]
        assert item["track_id"] == 3 and item["plex_id"] == 103
        assert item["artist"] == "Real Artist" and item["album"] == "Real Album"
        assert item["year"] == 2001 and item["popularity"] == 70
        assert item["sources"]
        assert len(item["score"]["availability"]) == 6
    assert normal.json()["sonic_coverage"] == {"candidates": 1, "with_vector": 1}
    assert responses[-1].json()["recommendations"][0]["score"]["availability"]["sonic"] == "mixed"


def test_recommend_method_parameter_roundtrip(workflow):
    client, _ctx, _plex = workflow
    for method in ("average", "frequency"):
        response = client.post("/recommend", data={"seed_ids": "1,2", "method": method})
        assert response.status_code == 200, response.text
        assert response.json()["method"] == method
        assert response.json()["recommendations"][0]["track_id"] == 3
    bad = client.post("/recommend", data={"seed_ids": "1", "method": "median"})
    assert bad.status_code == 422


def test_create_and_populate_use_approved_ids_without_another_recommendation(workflow, monkeypatch):
    client, _ctx, plex = workflow
    assert client.post("/recommend", data={"seed_ids": "1,2"}).status_code == 200

    def no_recompute(*_a, **_kw):
        raise AssertionError("must use approved IDs")

    monkeypatch.setattr(recommend, "get_recommendations", no_recompute)
    monkeypatch.setattr(populate, "populate_playlist_recommendations", no_recompute)
    created = client.post("/playlists/create", data={
        "name": "Approved", "seed_ids": "2,1", "track_ids": "3", "limit": "999",
    })
    assert created.status_code == 200, created.text
    assert plex.created == [[102, 101, 103]]
    assert created.json()["recommendation_count"] == 1
    applied = client.post("/playlists/fixture/populate", data={"track_ids": "3"})
    assert applied.status_code == 200, applied.text
    assert plex.added == [("fixture", [103])]


@pytest.mark.parametrize("selection", [
    None, "", "3,bad", "3,", "-1", "999999", "9223372036854775808", "9" * 5000,
])
def test_bad_selection_never_regenerates_or_partially_writes(workflow, selection):
    client, _ctx, plex = workflow
    fields = {} if selection is None else {"track_ids": selection}
    create = client.post("/playlists/create", data={"name": "Rejected", "seed_ids": "1", **fields})
    append = client.post("/playlists/fixture/populate", data=fields)
    assert create.status_code in (400, 404, 422)
    assert append.status_code in (400, 404, 422)
    assert plex.created == [] and plex.added == []


def test_write_openapi_requires_approved_ids_without_scoring_parameters():
    schema = create_app().openapi()
    for path, fields in (
        ("/playlists/create", {"name", "seed_ids", "track_ids"}),
        ("/playlists/{playlist_id}/populate", {"track_ids"}),
    ):
        content = schema["paths"][path]["post"]["requestBody"]["content"]
        reference = content["application/x-www-form-urlencoded"]["schema"]["$ref"]
        body = schema["components"]["schemas"][reference.rsplit("/", 1)[1]]
        assert set(body["properties"]) == fields
        assert set(body["required"]) == fields
