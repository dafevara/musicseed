"""Plex sign-in routes — offline tests of the HTTP contract.

Every plex.tv call is stubbed at the handler boundary, so the suite runs with
no network. The contract under test: the browser gets a PIN and an account
name, never a Plex token.
"""

import musicseed_api.handlers.plex_auth as plex_auth_handlers
from fastapi.testclient import TestClient
from musicseed.services.plex_link import (
    PlexAccountInfo,
    PlexLinkResult,
    PlexLinkStart,
)
from musicseed_api.app import create_app
from musicseed_api.security import CSRF_ENDPOINT, CSRF_HEADER

ORIGIN = "http://localhost:8000"

START = PlexLinkStart(
    pin_id=7,
    code="ABCD",
    handoff="forward",
    auth_url="https://app.plex.tv/auth#?clientID=abc&code=ABCD",
    link_url="https://plex.tv/link",
    expires_in=1800,
)

ACCOUNT = PlexAccountInfo(
    id=42, username="dafevara", title="Dafevara", email="dafevara@example.com"
)


def test_create_pin_returns_code_and_urls(monkeypatch):
    captured: dict = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return START

    monkeypatch.setattr(plex_auth_handlers, "start_plex_link", fake_start)
    client = TestClient(create_app())
    token = client.get(CSRF_ENDPOINT).json()["token"]
    resp = client.post(
        "/auth/plex/pin",
        data={"handoff": "link", "forward_url": f"{ORIGIN}/setup"},
        headers={"origin": ORIGIN, CSRF_HEADER: token},
    )

    assert resp.status_code == 200
    assert captured["handoff"] == "link"
    assert captured["forward_url"] == f"{ORIGIN}/setup"
    # Locked contract: no token field can appear here.
    assert set(resp.json()) == {
        "pin_id", "code", "handoff", "auth_url", "link_url", "expires_in",
    }
    assert resp.json()["code"] == "ABCD"


def test_create_pin_defaults_to_the_forward_handoff(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        plex_auth_handlers,
        "start_plex_link",
        lambda **kwargs: captured.update(kwargs) or START,
    )
    resp = TestClient(create_app()).post("/auth/plex/pin", data={})

    assert resp.status_code == 200
    assert captured["handoff"] == "forward"
    assert captured["forward_url"] == ""


def test_create_pin_rejects_a_foreign_forward_url(monkeypatch):
    def fail(**_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("plex.tv must not be called for a rejected URL")

    monkeypatch.setattr(plex_auth_handlers, "start_plex_link", fail)
    client = TestClient(create_app())
    token = client.get(CSRF_ENDPOINT).json()["token"]
    resp = client.post(
        "/auth/plex/pin",
        data={"handoff": "forward", "forward_url": "https://evil.example.com/setup"},
        headers={"origin": ORIGIN, CSRF_HEADER: token},
    )

    assert resp.status_code == 400
    assert "this MusicSeed instance" in resp.json()["detail"]


def test_create_pin_rejects_a_non_http_forward_url(monkeypatch):
    monkeypatch.setattr(
        plex_auth_handlers, "start_plex_link", lambda **_kw: START
    )
    resp = TestClient(create_app()).post(
        "/auth/plex/pin",
        data={"handoff": "forward", "forward_url": "javascript:alert(1)"},
    )

    assert resp.status_code == 400
    assert "absolute http(s) URL" in resp.json()["detail"]


def test_create_pin_rejects_an_unknown_handoff(monkeypatch):
    monkeypatch.setattr(
        plex_auth_handlers, "start_plex_link", lambda **_kw: START
    )
    resp = TestClient(create_app()).post(
        "/auth/plex/pin", data={"handoff": "carrier-pigeon"}
    )

    assert resp.status_code == 400
    assert "Unknown Plex sign-in hand-off" in resp.json()["detail"]


def test_check_pin_reports_pending(monkeypatch):
    monkeypatch.setattr(
        plex_auth_handlers,
        "poll_plex_link",
        lambda pin_id: PlexLinkResult(linked=False, pending=True),
    )
    resp = TestClient(create_app()).get("/auth/plex/pin/7")

    assert resp.status_code == 200
    assert resp.json()["pending"] is True
    assert resp.json()["linked"] is False


def test_check_pin_reports_the_linked_account(monkeypatch):
    monkeypatch.setattr(
        plex_auth_handlers,
        "poll_plex_link",
        lambda pin_id: PlexLinkResult(
            linked=True, token_saved=True, account=ACCOUNT, servers=[]
        ),
    )
    body = TestClient(create_app()).get("/auth/plex/pin/7").json()

    assert body["linked"] is True
    assert body["account"]["title"] == "Dafevara"
    assert "token" not in body


def test_account_route_reports_unlinked(monkeypatch):
    monkeypatch.setattr(plex_auth_handlers, "get_plex_account", lambda: None)
    assert TestClient(create_app()).get("/auth/plex/account").json() == {
        "linked": False,
        "account": None,
    }


def test_account_route_reports_the_account(monkeypatch):
    monkeypatch.setattr(plex_auth_handlers, "get_plex_account", lambda: ACCOUNT)
    body = TestClient(create_app()).get("/auth/plex/account").json()

    assert body["linked"] is True
    assert body["account"]["email"] == "dafevara@example.com"
    assert "token" not in body["account"]


def test_unlink_route_clears_the_token(monkeypatch):
    monkeypatch.setattr(plex_auth_handlers, "unlink_plex", lambda: True)
    assert TestClient(create_app()).post("/auth/plex/unlink").json() == {
        "unlinked": True
    }
