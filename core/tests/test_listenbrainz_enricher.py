"""Unit tests for the ListenBrainz enrichment client — mocked HTTP, no network."""

import asyncio
import time

import httpx
from musicseed.enrichers.listenbrainz import ListenBrainzClient

MBID_A = "13dd61c7-ce73-4e97-9f0c-9f0e53144411"
MBID_B = "22ad712e-ce73-9f0c-4e97-9f0e53144411"


def _client_with_transport(handler, **kwargs) -> ListenBrainzClient:
    client = ListenBrainzClient(**kwargs)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def test_get_recording_popularity_parses_counts():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/1/popularity/recording"
        assert request.method == "POST"
        return httpx.Response(200, json=[
            {"recording_mbid": MBID_A, "total_listen_count": 1000, "total_user_count": 10},
            {"recording_mbid": MBID_B, "total_listen_count": None, "total_user_count": None},
        ])

    client = _client_with_transport(handler, requests_per_second=1000)
    results = asyncio.run(client.get_recording_popularity([MBID_A, MBID_B]))

    assert len(results) == 2
    assert results[0].recording_mbid == MBID_A
    assert results[0].total_listen_count == 1000
    assert results[0].total_user_count == 10
    # Unmatched MBIDs come back with null counts, order preserved.
    assert results[1].recording_mbid == MBID_B
    assert results[1].total_listen_count is None
    assert results[1].total_user_count is None


def test_empty_mbids_returns_empty_without_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP request expected for an empty MBID list")

    client = _client_with_transport(handler)
    assert asyncio.run(client.get_recording_popularity([])) == []


def test_429_retry_honors_retry_after():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=[
            {"recording_mbid": MBID_A, "total_listen_count": 5, "total_user_count": 1},
        ])

    client = _client_with_transport(handler, requests_per_second=1000)
    results = asyncio.run(client.get_recording_popularity([MBID_A]))

    assert len(calls) == 2
    assert results[0].total_listen_count == 5


def test_request_error_retries_then_raises():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("boom", request=request)

    client = _client_with_transport(handler, requests_per_second=1000)
    try:
        asyncio.run(client.get_recording_popularity([MBID_A]))
        raise AssertionError("expected ConnectError after retries")
    except httpx.ConnectError:
        pass
    assert len(calls) == 3


def test_token_header_sent_when_configured():
    async def check():
        async with ListenBrainzClient(token="secret-token") as client:
            assert client._client.headers["Authorization"] == "Token secret-token"
        async with ListenBrainzClient() as client:
            assert "Authorization" not in client._client.headers

    asyncio.run(check())


def test_throttle_spaces_requests():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    # 20 req/s => at least 50ms between request starts.
    client = _client_with_transport(handler, requests_per_second=20)

    async def two_requests():
        start = time.monotonic()
        await client.get_recording_popularity([MBID_A])
        await client.get_recording_popularity([MBID_A])
        return time.monotonic() - start

    elapsed = asyncio.run(two_requests())
    assert elapsed >= 0.04
