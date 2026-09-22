"""Real ORM -> recommender/populate -> detached service DTOs and exact Plex writes."""

import json

import pytest
from musicseed.clients.plex import MediaItem, Playlist, PlexAPIError
from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.db.models import Album, Artist, Genre, Style, Track, TrackVector
from musicseed.db.session import init_db
from musicseed.exceptions import NotFoundError
from musicseed.recommender.scoring import SIGNALS
from musicseed.services import playlist_tracks, populate, recommend


def vector(first=1.0):
    return [first, *([0.0] * 49)]


@pytest.fixture
def library(tmp_path, monkeypatch):
    ctx = MusicSeedContext(Config.model_validate({
        "database": {"path": str(tmp_path / "recommend.db")},
        "plex": {"token": "fixture-token"},
    }))
    init_db(ctx)
    with ctx.session() as session:
        rock, indie = Genre(name="rock"), Style(name="indie")
        album = Album(title="Fixture Album", year=1999)
        tracks = [
            Track(title="Seed A", plex_id=101, artist=Artist(name="Seed Artist A"),
                  album=album, year=1999, spotify_popularity=50, genres=[rock], styles=[indie]),
            Track(title="Seed B", plex_id=102, artist=Artist(name="Seed Artist B")),
            Track(title="Candidate", plex_id=103, artist=Artist(name="Candidate Artist"),
                  album=album, year=2000, popularity_score=0.6, genres=[rock], styles=[indie]),
            Track(title="Sparse", plex_id=104, artist=Artist(name="Sparse Artist")),
        ]
        session.add_all(tracks)
        session.add_all([
            TrackVector(plex_id=101, vector=vector()),
            TrackVector(plex_id=103, vector=vector()),
            TrackVector(plex_id=104, vector=vector(0)),
        ])
        session.flush()
        ids = [t.id for t in tracks]

    class FakePlex:
        def __init__(self):
            self.created = []
            self.added = []

        def get_playlist(self, _id):
            return Playlist(rating_key="playlist", title="Fixture Playlist", leaf_count=2)

        def find_playlist(self, _name):
            return None

        def get_playlist_tracks(self, _id):
            return [MediaItem(rating_key="101"), MediaItem(rating_key="102")]

        def add_to_playlist(self, playlist_id, plex_ids):
            self.added.append((playlist_id, list(plex_ids)))

        def create_playlist(self, name, plex_ids):
            self.created.append(list(plex_ids))
            return Playlist(rating_key="new", title=name, leaf_count=len(plex_ids))

    plex = FakePlex()
    monkeypatch.setattr(populate, "_plex_client", lambda _ctx=None: plex)
    monkeypatch.setattr(playlist_tracks, "PlexClient", lambda **_kw: plex)
    yield ctx, ids, plex
    ctx.engine.dispose()


def test_real_services_serialize_after_sessions_and_engine_are_closed(library, monkeypatch):
    ctx, ids, _plex = library
    normal = recommend.get_recommendations(seed_ids=ids[:2], limit=2, context=ctx)
    average = populate.get_populate_recommendations("playlist", method="average", context=ctx)
    frequency = populate.get_populate_recommendations("playlist", method="frequency", context=ctx)
    ctx.engine.dispose()

    def no_more_sessions():
        raise AssertionError("serialization must not access ORM state")

    monkeypatch.setattr(ctx, "session", no_more_sessions)
    for result in (normal, average, frequency):
        data = json.loads(result.model_dump_json())
        assert len(data["recommendations"]) == 2
        candidate = next(r for r in data["recommendations"] if r["track"]["id"] == ids[2])
        assert candidate["track"] == {
            "id": ids[2], "title": "Candidate", "artist": "Candidate Artist",
            "album": "Fixture Album", "year": 2000, "popularity": 60.0, "plex_id": 103,
        }
        assert candidate["sources"]
        assert set(candidate["score"]["availability"]) == set(SIGNALS)
    assert normal.sonic_coverage.candidates == 2
    assert normal.sonic_coverage.with_vector == 1  # stored zero vector is unusable
    voted = next(r for r in frequency.recommendations if r.track.id == ids[2])
    assert voted.sources == [str(i) for i in ids[:2]]
    assert voted.score.availability["sonic"] == "mixed"
    assert voted.score.availability["style"] == "mixed"
    assert voted.score.availability["novelty"] == "observed"


def test_approved_ids_are_used_without_recomputing_or_reordering(library, monkeypatch):
    ctx, ids, plex = library
    preview = recommend.get_recommendations(seed_ids=ids[:2], limit=2, context=ctx)
    assert preview.recommendations

    def no_recompute(*_a, **_kw):
        raise AssertionError("approved selection must never be recomputed")

    monkeypatch.setattr(recommend, "get_recommendations", no_recompute)
    monkeypatch.setattr(populate, "populate_playlist_recommendations", no_recompute)
    # Deliberately reverse rank order and duplicate an ID; preserve first occurrence.
    created = playlist_tracks.create_playlist_from_tracks("Approved", [ids[3], ids[2], ids[3]],
                                                         context=ctx)
    assert plex.created == [[104, 103]]
    assert [track.id for track in created.tracks] == [ids[3], ids[2]]
    applied = populate.populate_playlist("playlist", track_ids=[ids[3], ids[2]], context=ctx)
    assert plex.added == [("playlist", [104, 103])]
    assert applied.added_count == 2
    assert applied.recommendations == []  # no fabricated scores for an explicit selection
    ctx.engine.dispose()
    json.loads(created.model_dump_json())
    json.loads(applied.model_dump_json())


def test_stale_selection_fails_before_any_write_and_empty_never_regenerates(library):
    ctx, ids, plex = library
    for selected in ([ids[2], 999999], [999999]):
        with pytest.raises(NotFoundError, match="Refresh the preview"):
            playlist_tracks.create_playlist_from_tracks("Stale", selected, context=ctx)
        with pytest.raises(NotFoundError, match="Refresh the preview"):
            populate.populate_playlist("playlist", track_ids=selected, context=ctx)
    assert not plex.created and not plex.added
    result = populate.populate_playlist("playlist", track_ids=[], context=ctx)
    assert result.added_count == 0
    assert not plex.added


def test_unmapped_approved_track_rejects_the_whole_write(library):
    ctx, ids, plex = library
    with ctx.session() as session:
        session.get(Track, ids[2]).plex_id = None
    with pytest.raises(NotFoundError):
        playlist_tracks.create_playlist_from_tracks("Stale", ids[2:], context=ctx)
    assert not plex.created


def test_populate_reconciles_partially_present_tracks(library, monkeypatch):
    ctx, ids, plex = library
    # Playlist already contains 104; only 103 should be added.
    monkeypatch.setattr(plex, "get_playlist_tracks", lambda _id: [
        MediaItem(rating_key="101"), MediaItem(rating_key="102"),
        MediaItem(rating_key="104"),
    ])
    applied = populate.populate_playlist("playlist", track_ids=[ids[3], ids[2]], context=ctx)
    assert plex.added == [("playlist", [103])]
    assert applied.added_count == 1
    assert applied.already_present_count == 1


def test_populate_skips_write_when_all_tracks_already_present(library, monkeypatch):
    ctx, ids, plex = library
    # Retry after a lost response: the whole selection is already there.
    monkeypatch.setattr(plex, "get_playlist_tracks", lambda _id: [
        MediaItem(rating_key="101"), MediaItem(rating_key="102"),
        MediaItem(rating_key="104"), MediaItem(rating_key="103"),
    ])
    applied = populate.populate_playlist("playlist", track_ids=[ids[3], ids[2]], context=ctx)
    assert not plex.added
    assert applied.added_count == 0
    assert applied.already_present_count == 2


def test_create_playlist_is_idempotent_on_same_name_and_contents(library, monkeypatch):
    ctx, ids, plex = library
    existing = Playlist(rating_key="existing", title="Approved", leaf_count=2)
    monkeypatch.setattr(plex, "find_playlist", lambda _name: existing)
    monkeypatch.setattr(plex, "get_playlist_tracks", lambda _id: [
        MediaItem(rating_key="104"), MediaItem(rating_key="103"),
    ])
    result = playlist_tracks.create_playlist_from_tracks(
        "Approved", [ids[3], ids[2]], context=ctx
    )
    assert result.playlist.rating_key == "existing"
    assert not plex.created


def test_create_playlist_conflicts_when_name_exists_with_different_tracks(library, monkeypatch):
    ctx, ids, plex = library
    existing = Playlist(rating_key="existing", title="Approved", leaf_count=1)
    monkeypatch.setattr(plex, "find_playlist", lambda _name: existing)
    monkeypatch.setattr(plex, "get_playlist_tracks", lambda _id: [MediaItem(rating_key="101")])
    with pytest.raises(PlexAPIError):
        playlist_tracks.create_playlist_from_tracks(
            "Approved", [ids[3], ids[2]], context=ctx
        )
    assert not plex.created
