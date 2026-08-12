"""Cooperative cancellation tests for the enrichment pipeline."""

import asyncio

import musicseed.config as config_module
import pytest
from musicseed.config import Config, set_config
from musicseed.db.session import init_db, reset_engine
from musicseed.enrichers.pipeline import (
    enrich_tracks,
    enrich_tracks_with_listenbrainz,
)


class FakeProgress:
    def add_task(self, *args, **kwargs):
        return 0

    def advance(self, *args, **kwargs):
        pass


class FakeListenBrainzClient:
    def __init__(self):
        self.calls = 0

    async def get_recording_popularity(self, mbids):
        self.calls += 1
        return []


class _MatchResult:
    matched = False
    spotify_track = None


class FakeSpotifyClient:
    def __init__(self):
        self.calls = 0

    async def match_track(self, **kwargs):
        self.calls += 1
        return _MatchResult()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    cfg = Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    set_config(cfg)
    reset_engine()
    init_db()
    yield
    config_module._config = None
    reset_engine()


def test_listenbrainz_cancellation_stops_before_first_batch():
    client = FakeListenBrainzClient()
    tracks = [{"id": i, "mbid": f"mbid-{i}"} for i in range(10)]

    matched, unmatched, errors = asyncio.run(
        enrich_tracks_with_listenbrainz(
            tracks, client, FakeProgress(), 5,
            should_cancel=lambda: True,
        )
    )

    assert client.calls == 0
    assert (matched, unmatched, errors) == (0, 0, 0)


def test_spotify_cancellation_stops_before_first_track():
    client = FakeSpotifyClient()
    tracks = [{"id": i, "title": "t", "artist": "a", "album": None} for i in range(10)]

    matched, unmatched, errors = asyncio.run(
        enrich_tracks(
            tracks, client, FakeProgress(), batch_size=5,
            should_cancel=lambda: True,
        )
    )

    assert client.calls == 0
    assert (matched, unmatched, errors) == (0, 0, 0)


def test_spotify_completes_when_not_cancelled():
    client = FakeSpotifyClient()
    tracks = [{"id": 1, "title": "t", "artist": "a", "album": None}]

    matched, unmatched, errors = asyncio.run(
        enrich_tracks(tracks, client, FakeProgress(), batch_size=5)
    )

    assert client.calls == 1


def test_spotify_opens_one_session_per_batch(monkeypatch):
    from contextlib import contextmanager

    import musicseed.enrichers.pipeline as pl

    real_get_session = pl.get_session
    opens = {"n": 0}

    @contextmanager
    def counting_session():
        opens["n"] += 1
        with real_get_session() as session:
            yield session

    monkeypatch.setattr(pl, "get_session", counting_session)
    client = FakeSpotifyClient()
    tracks = [{"id": i, "title": "t", "artist": "a", "album": None} for i in range(5)]

    asyncio.run(enrich_tracks(tracks, client, FakeProgress(), batch_size=2))

    assert opens["n"] == 3  # ceil(5 / 2) sessions — one per batch
