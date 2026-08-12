"""Cooperative cancellation tests for the enrichment and import pipelines."""

import asyncio

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


class FakeSpotifyClient:
    def __init__(self):
        self.calls = 0

    async def match_track(self, **kwargs):
        self.calls += 1
        return None


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def get(self, *args, **kwargs):
        return None


def test_listenbrainz_cancellation_stops_before_first_batch():
    client = FakeListenBrainzClient()
    tracks = [{"id": i, "mbid": f"mbid-{i}"} for i in range(10)]

    matched, unmatched, errors = asyncio.run(
        enrich_tracks_with_listenbrainz(
            None, tracks, client, FakeProgress(), 5,
            should_cancel=lambda: True,
        )
    )

    assert client.calls == 0
    assert (matched, unmatched, errors) == (0, 0, 0)


def test_spotify_cancellation_stops_before_first_track():
    client = FakeSpotifyClient()
    session = FakeSession()
    tracks = [{"id": i, "title": "t", "artist": "a", "album": None} for i in range(10)]

    matched, unmatched, errors = asyncio.run(
        enrich_tracks(
            session, tracks, client, FakeProgress(),
            should_cancel=lambda: True,
        )
    )

    assert client.calls == 0
    assert (matched, unmatched, errors) == (0, 0, 0)


def test_spotify_completes_when_not_cancelled():
    client = FakeSpotifyClient()
    session = FakeSession()
    tracks = [{"id": 1, "title": "t", "artist": "a", "album": None}]

    asyncio.run(
        enrich_tracks(session, tracks, client, FakeProgress())
    )

    assert client.calls == 1
