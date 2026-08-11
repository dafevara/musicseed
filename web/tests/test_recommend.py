"""Recommend screen tests: page render, typeahead, seeds, and results.

All patches target the imported names in the web route module
(``musicseed_web.routes.recommend``) so they affect the functions the
routes actually call at runtime.
"""

import pytest
from fastapi.testclient import TestClient
from musicseed.db.models import Album, Artist, Track
from musicseed.exceptions import NotFoundError
from musicseed.recommender.playlist import Recommendation
from musicseed.recommender.scoring import ScoreBreakdown
from musicseed.services.recommend import RecommendationResult
from musicseed_web.app import create_app
from musicseed_web.nav import SECTIONS, active_section
from musicseed_web.routes import recommend

client = TestClient(create_app())


def _fake_artist(id_: int, name: str) -> Artist:
    a = Artist(id=id_, name=name)
    return a


def _fake_track(id_: int, title: str, artist: Artist, year: int = 2020) -> Track:
    album = Album(id=id_, title=f"Album {id_}", year=year)
    return Track(id=id_, title=title, artist=artist, album=album, year=year)


# ── page render ──────────────────────────────────────────────────────


def test_recommend_page_renders() -> None:
    response = client.get("/recommend")
    assert response.status_code == 200
    assert "Seed tracks" in response.text
    assert "Filters" in response.text


# ── navigation ──────────────────────────────────────────────────────


def test_recommend_section_is_available() -> None:
    rec = [s for s in SECTIONS if s.key == "recommend"][0]
    assert rec.available
    assert rec.href == "/recommend"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/recommend", "recommend"),
        ("/recommend/typeahead", "recommend"),
        ("/recommend/seeds", "recommend"),
        ("/recommend/results", "recommend"),
        ("/recommend/typeahead?q=foo", "recommend"),
    ],
)
def test_recommend_routes_resolve_active_section(path: str, expected: str) -> None:
    assert active_section(path) == expected


def test_recommend_page_has_navigation() -> None:
    response = client.get("/recommend")
    assert 'aria-current="page"' in response.text
    assert "Recommend" in response.text


# ── typeahead ───────────────────────────────────────────────────────


def test_typeahead_short_query_returns_empty(monkeypatch) -> None:
    response = client.get("/recommend/typeahead?q=a")
    assert response.status_code == 200
    assert response.text == ""


def test_typeahead_returns_matches(monkeypatch) -> None:
    artist = _fake_artist(1, "Radiohead")
    tracks = [_fake_track(1, "Karma Police", artist)]
    monkeypatch.setattr(recommend, "typeahead_search", lambda q, exclude_ids=None: tracks)

    response = client.get("/recommend/typeahead?q=karma")
    assert response.status_code == 200
    assert "Karma Police" in response.text
    assert "Radiohead" in response.text


def test_typeahead_excludes_existing_seeds(monkeypatch) -> None:
    artist = _fake_artist(1, "Artist")
    tracks = [_fake_track(2, "Other Song", artist)]
    monkeypatch.setattr(recommend, "typeahead_search", lambda q, exclude_ids=None: tracks)

    response = client.get("/recommend/typeahead?q=other&seed_ids=1")
    assert response.status_code == 200
    assert "Other Song" in response.text


def test_typeahead_empty_results(monkeypatch) -> None:
    monkeypatch.setattr(recommend, "typeahead_search", lambda q, exclude_ids=None: [])

    response = client.get("/recommend/typeahead?q=zzzznonexistent")
    assert response.status_code == 200
    assert "Karma" not in response.text
    assert "Radiohead" not in response.text


# ── seeds ───────────────────────────────────────────────────────────


def test_add_seed(monkeypatch) -> None:
    artist = _fake_artist(1, "Radiohead")
    tracks = [_fake_track(1, "Karma Police", artist)]
    monkeypatch.setattr(recommend, "load_seed_tracks", lambda ids: tracks)

    response = client.post("/recommend/seeds", data={
        "action": "add", "track_id": 1, "seed_ids": "",
    })
    assert response.status_code == 200
    assert "Karma Police" in response.text
    assert "Radiohead" in response.text
    assert "HX-Trigger" in response.headers
    assert "seedsChanged" in response.headers["HX-Trigger"]


def test_remove_seed(monkeypatch) -> None:
    monkeypatch.setattr(recommend, "load_seed_tracks", lambda ids: [])

    response = client.post("/recommend/seeds", data={
        "action": "remove", "track_id": 1, "seed_ids": "1",
    })
    assert response.status_code == 200
    assert "HX-Trigger" in response.headers


def test_remove_last_seed_shows_empty(monkeypatch) -> None:
    monkeypatch.setattr(recommend, "load_seed_tracks", lambda ids: [])

    response = client.post("/recommend/seeds", data={
        "action": "remove", "track_id": 1, "seed_ids": "1",
    })
    assert response.status_code == 200
    assert "seed-list" not in response.text


# ── results ─────────────────────────────────────────────────────────


def _make_result(seed_tracks: list[Track], recs: list[Recommendation]) -> RecommendationResult:
    return RecommendationResult(seed_tracks=seed_tracks, recommendations=recs)


def _make_recommendation(track: Track, total: float = 0.75) -> Recommendation:
    score = ScoreBreakdown(
        total=total, sonic=0.7, popularity=0.6, style=0.5, genre=0.8, era=0.4, novelty=0.3,
    )
    return Recommendation(track=track, score=score, sources=["sonic", "style"])


def test_results_renders_recommendations(monkeypatch) -> None:
    artist = _fake_artist(1, "Radiohead")
    seed = _fake_track(1, "Karma Police", artist)
    result_track = _fake_track(2, "Paranoid Android", artist)
    rec = _make_recommendation(result_track)
    result = _make_result([seed], [rec])
    monkeypatch.setattr(recommend, "run_recommendations", lambda **kw: result)

    response = client.post("/recommend/results", data={"seed_ids": "1"})
    assert response.status_code == 200
    assert "Paranoid Android" in response.text
    assert "0.75" in response.text


def test_results_shows_prompt_when_no_seeds(monkeypatch) -> None:
    response = client.post("/recommend/results", data={"seed_ids": ""})
    assert response.status_code == 200
    assert "Add one or more seed tracks" in response.text


def test_results_handles_unresolvable_seed(monkeypatch) -> None:
    monkeypatch.setattr(
        recommend, "run_recommendations",
        lambda **kw: (_ for _ in ()).throw(NotFoundError("No seed track matched: ghost")),
    )

    response = client.post("/recommend/results", data={"seed_ids": "999"})
    assert response.status_code == 200
    assert "No seed track matched" in response.text


def test_results_passes_filters_to_service(monkeypatch) -> None:
    captured: dict = {}

    def capture(**kw):
        captured.update(kw)
        artist = _fake_artist(1, "A")
        seed = _fake_track(1, "T", artist)
        return _make_result([seed], [])

    monkeypatch.setattr(recommend, "run_recommendations", capture)

    response = client.post("/recommend/results", data={
        "seed_ids": "1",
        "limit": "25",
        "year_min": "1990",
        "year_max": "2010",
        "max_tracks_per_artist": "2",
        "min_score": "0.5",
    })
    assert response.status_code == 200
    assert captured["limit"] == 25
    assert captured["year_min"] == 1990
    assert captured["year_max"] == 2010
    assert captured["max_tracks_per_artist"] == 2
    assert captured["min_score"] == 0.5
    assert captured["seed_ids"] == [1]


def test_results_shows_empty_when_no_matches(monkeypatch) -> None:
    artist = _fake_artist(1, "A")
    seed = _fake_track(1, "T", artist)
    result = _make_result([seed], [])
    monkeypatch.setattr(recommend, "run_recommendations", lambda **kw: result)

    response = client.post("/recommend/results", data={"seed_ids": "1"})
    assert response.status_code == 200
    assert "No recommendations found" in response.text
