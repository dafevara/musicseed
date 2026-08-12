"""Typeahead search service tests."""

import musicseed.config as config_module
import pytest
from musicseed.config import Config, set_config
from musicseed.db.models import Artist, Track
from musicseed.db.session import get_session, init_db, reset_engine
from musicseed.services.typeahead import search_tracks


@pytest.fixture(autouse=True)
def seeded_db(tmp_path):
    cfg = Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    set_config(cfg)
    reset_engine()
    init_db()
    with get_session() as session:
        beatles = Artist(name="The Beatles")
        radiohead = Artist(name="Radiohead")
        session.add_all([beatles, radiohead])
        session.flush()
        session.add_all([
            Track(title="Abbey Road", artist_id=beatles.id, year=1969),
            Track(title="Revolver", artist_id=beatles.id, year=1966),
            Track(title="OK Computer", artist_id=radiohead.id, year=1997),
            Track(title="Kid A", artist_id=radiohead.id, year=2000),
        ])
        session.add_all(
            [Track(title=f"Song {i:02d}") for i in range(1, 13)]
        )
    yield
    config_module._config = None
    reset_engine()


def test_short_query_returns_empty():
    assert search_tracks("a") == []
    assert search_tracks("") == []


def test_search_by_title():
    results = search_tracks("abbey")
    assert [r.title for r in results] == ["Abbey Road"]


def test_search_by_artist():
    results = search_tracks("radiohead")
    assert {r.title for r in results} == {"OK Computer", "Kid A"}
    assert all(r.artist == "Radiohead" for r in results)


def test_ordering_by_title():
    results = search_tracks("beatles")
    assert [r.title for r in results] == ["Abbey Road", "Revolver"]


def test_exclusions():
    all_results = search_tracks("radiohead")
    excluded_id = all_results[0].id
    results = search_tracks("radiohead", exclude_ids=[excluded_id])
    assert all(r.id != excluded_id for r in results)
    assert len(results) == len(all_results) - 1


def test_default_limit_is_ten():
    results = search_tracks("song")
    assert len(results) == 10


def test_explicit_limit():
    results = search_tracks("song", limit=5)
    assert len(results) == 5
