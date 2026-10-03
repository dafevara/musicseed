"""Browser protection middleware: host allowlist, origin check, CSRF token."""

from fastapi.testclient import TestClient
from musicseed_api.app import create_app
from musicseed_api.security import (
    CSRF_ENDPOINT,
    CSRF_HEADER,
    get_csrf_secret,
    host_allowed,
    issue_csrf_token,
    verify_csrf_token,
)

client = TestClient(create_app())


def _token() -> str:
    return client.get(CSRF_ENDPOINT).json()["token"]


def test_csrf_endpoint_returns_token():
    resp = client.get(CSRF_ENDPOINT)
    assert resp.status_code == 200
    assert resp.json()["token"]


def test_host_allowed_defaults():
    assert host_allowed("127.0.0.1:8789", [])
    assert host_allowed("localhost:8789", [])
    assert host_allowed("[::1]:8789", [])
    assert host_allowed("192.168.1.10", [])
    assert not host_allowed("evil.example.com", [])
    assert host_allowed("musicseed.lan", ["musicseed.lan"])
    assert not host_allowed("musicseed.lan", [])


def test_csrf_roundtrip():
    secret = get_csrf_secret()
    token = issue_csrf_token(secret)
    assert verify_csrf_token(secret, token)
    assert not verify_csrf_token(secret, "bogus")
    assert not verify_csrf_token(secret, "")


def test_mutating_browser_request_requires_csrf():
    token = _token()
    # A browser Origin without a token is rejected before any handler runs.
    resp = client.post("/auth/plex/unlink", headers={"Origin": "http://127.0.0.1:8789"})
    assert resp.status_code == 403
    # With the token the request proceeds.
    resp = client.post(
        "/auth/plex/unlink",
        headers={"Origin": "http://127.0.0.1:8789", CSRF_HEADER: token},
    )
    assert resp.status_code == 200


def test_cross_site_origin_rejected_even_with_token():
    token = _token()
    resp = client.post(
        "/auth/plex/unlink",
        headers={"Origin": "http://evil.example.com", CSRF_HEADER: token},
    )
    assert resp.status_code == 403


def test_non_browser_mutation_exempt():
    # No Origin/Referer means a non-browser client (CLI, curl, MCP): CSRF skipped.
    resp = client.post("/auth/plex/unlink")
    assert resp.status_code == 200


def test_unexpected_host_rejected():
    resp = client.get("/discovery", headers={"Host": "evil.example.com"})
    assert resp.status_code == 400


def test_allowed_extra_host_accepted():
    from musicseed.config import get_config

    cfg = get_config()
    cfg.security.allowed_hosts.append("musicseed.lan")
    resp = client.get("/discovery", headers={"Host": "musicseed.lan"})
    assert resp.status_code == 200
