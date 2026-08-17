"""Unit tests for the Spotify enrichment client — mocked HTTP, no network."""

import asyncio
import base64

import httpx
import pytest
from musicseed.enrichers.spotify import (
    SpotifyClient,
    SpotifyTrack,
    normalize_string,
    similarity,
)

TRACK_JSON = {
    "id": "spotify-1",
    "name": "Closer",
    "artists": [{"name": "Nine Inch Nails"}],
    "album": {"name": "The Downward Spiral"},
    "popularity": 72,
    "duration_ms": 373000,
}


def _client_with_transport(handler, **kwargs) -> SpotifyClient:
    client = SpotifyClient("cid", "secret", requests_per_second=1000, **kwargs)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._semaphore = asyncio.Semaphore(client.concurrency)
    return client


def _auth_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})


# ------------------------------------------------------------ string matching


def test_normalize_string_strips_accents_case_and_punctuation():
    assert normalize_string("  Björk — Hyperballad! ") == "bjork hyperballad"
    assert normalize_string("") == ""


def test_similarity_identical_after_normalization():
    assert similarity("The Downward Spiral", "the downward spiral") == 1.0


# ---------------------------------------------------------------- score_match


def test_score_match_perfect_is_one():
    client = SpotifyClient("cid", "secret")
    track = SpotifyTrack(
        spotify_id="x", name="Closer", artist="Nine Inch Nails",
        album="The Downward Spiral", popularity=72, duration_ms=373000,
    )
    score = client.score_match("Closer", "Nine Inch Nails", "The Downward Spiral", 373000, track)
    assert score == pytest.approx(1.0)


def test_score_match_duration_bands():
    client = SpotifyClient("cid", "secret")
    track = SpotifyTrack(
        spotify_id="x", name="Closer", artist="Nine Inch Nails",
        album="The Downward Spiral", popularity=72, duration_ms=373000,
    )
    close = client.score_match("Closer", "Nine Inch Nails", "The Downward Spiral", 374000, track)
    far = client.score_match("Closer", "Nine Inch Nails", "The Downward Spiral", 500000, track)
    assert close > far


def test_score_match_defaults_when_album_and_duration_missing():
    client = SpotifyClient("cid", "secret")
    track = SpotifyTrack(
        spotify_id="x", name="Closer", artist="Nine Inch Nails",
        album="The Downward Spiral", popularity=72, duration_ms=373000,
    )
    # title 1.0*0.4 + artist 1.0*0.4 + album 0.5*0.1 + duration 0.5*0.1
    score = client.score_match("Closer", "Nine Inch Nails", None, None, track)
    assert score == pytest.approx(0.9)


# -------------------------------------------------------------------- token


def test_ensure_token_uses_client_credentials_and_caches():
    auth_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            auth_calls.append(request)
            expected = base64.b64encode(b"cid:secret").decode()
            assert request.headers["Authorization"] == f"Basic {expected}"
            assert request.content == b"grant_type=client_credentials"
            return _auth_handler(request)
        raise AssertionError(f"unexpected request: {request.url}")

    client = _client_with_transport(handler)

    async def run():
        first = await client._ensure_token()
        second = await client._ensure_token()
        return first, second

    first, second = asyncio.run(run())
    assert first == second == "tok"
    assert len(auth_calls) == 1  # second call served from cache


# ------------------------------------------------------------------- search


def _spotify_handler(search_payload, search_calls=None, auth_payload=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return auth_payload or _auth_handler(request)
        if request.url.path == "/v1/search":
            if search_calls is not None:
                search_calls.append(request)
            return search_payload
        raise AssertionError(f"unexpected request: {request.url}")

    return handler


def test_search_track_parses_results():
    payload = httpx.Response(200, json={"tracks": {"items": [TRACK_JSON]}})
    client = _client_with_transport(_spotify_handler(payload))

    tracks = asyncio.run(client.search_track("Closer (Remastered)", "Nine Inch Nails"))

    assert len(tracks) == 1
    track = tracks[0]
    assert track.spotify_id == "spotify-1"
    assert track.name == "Closer"
    assert track.artist == "Nine Inch Nails"
    assert track.album == "The Downward Spiral"
    assert track.popularity == 72
    assert track.duration_ms == 373000


def test_search_track_429_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return _auth_handler(request)
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"tracks": {"items": [TRACK_JSON]}})

    client = _client_with_transport(handler)
    tracks = asyncio.run(client.search_track("Closer", "Nine Inch Nails"))

    assert len(calls) == 2
    assert tracks[0].spotify_id == "spotify-1"


# --------------------------------------------------------------- batch get


def test_get_tracks_skips_null_entries():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/token":
            return _auth_handler(request)
        assert request.url.path == "/v1/tracks"
        assert request.url.params["ids"] == "spotify-1,spotify-2"
        return httpx.Response(200, json={"tracks": [TRACK_JSON, None]})

    client = _client_with_transport(handler)
    tracks = asyncio.run(client.get_tracks(["spotify-1", "spotify-2"]))

    assert len(tracks) == 1
    assert tracks[0].spotify_id == "spotify-1"


def test_get_tracks_rejects_over_50_ids():
    client = SpotifyClient("cid", "secret")
    with pytest.raises(ValueError, match="Max 50"):
        asyncio.run(client.get_tracks(["x"] * 51))


# -------------------------------------------------------------- match_track


def test_match_track_above_threshold_matches():
    client = SpotifyClient("cid", "secret")
    candidate = SpotifyTrack(
        spotify_id="x", name="Closer", artist="Nine Inch Nails",
        album="The Downward Spiral", popularity=72, duration_ms=373000,
    )

    async def fake_search(title, artist, album=None):
        return [candidate]

    client.search_track = fake_search
    result = asyncio.run(
        client.match_track("Closer", "Nine Inch Nails", "The Downward Spiral", 373000)
    )
    assert result.matched
    assert result.spotify_track == candidate
    assert result.score == pytest.approx(1.0)


def test_match_track_below_threshold_returns_no_match():
    client = SpotifyClient("cid", "secret")
    candidate = SpotifyTrack(
        spotify_id="x", name="Completely Different", artist="Other Artist",
        album="Other Album", popularity=10, duration_ms=100000,
    )

    async def fake_search(title, artist, album=None):
        return [candidate]

    client.search_track = fake_search
    result = asyncio.run(
        client.match_track("Closer", "Nine Inch Nails", "The Downward Spiral", 373000)
    )
    assert not result.matched
    assert result.spotify_track is None
    assert result.score < 0.7


def test_match_track_no_candidates():
    client = SpotifyClient("cid", "secret")

    async def fake_search(title, artist, album=None):
        return []

    client.search_track = fake_search
    result = asyncio.run(client.match_track("Nope", "Nobody"))
    assert not result.matched
    assert result.score == 0.0
