"""Tests for services.plex_discovery — no real multicast or network involved."""

import socket

import httpx
import pytest
from musicseed.services import plex_discovery
from musicseed.services.plex_discovery import discover_plex_servers

GDM_REPLY = (
    "HTTP/1.0 200 OK\r\n"
    "Content-Type: plex/media-server\r\n"
    "Host: 41281637cb044f40b52ceba2b604921d.plex.direct\r\n"
    "Name: Living Room\r\n"
    "Port: 32400\r\n"
    "Product: Plex Media Server\r\n"
    "Resource-Identifier: 3309a4b35976865b17593c74cb3f5b447c520cbf\r\n"
    "Updated-At: 1786575042\r\n"
    "Version: 1.43.3.10828\r\n"
    "\r\n"
).encode()

SSDP_REPLY = (
    "HTTP/1.1 200 OK\r\n"
    "LOCATION: http://192.168.1.7:32400/ssdp/device-desc.xml\r\n"
    "SERVER: Linux/3.x, UPnP/1.0, Plex Media Server/1.40.5.8897\r\n"
    "ST: urn:plex-com:service:pms:1\r\n"
    "USN: uuid:abc::urn:plex-com:service:pms:1\r\n"
    "\r\n"
).encode()

ACCOUNT_RESOURCES = [
    {
        "name": "Caladan",
        "product": "Plex Media Server",
        "productVersion": "1.43.3.10828",
        "clientIdentifier": "3309a4b35976865b17593c74cb3f5b447c520cbf",
        "provides": "server",
        "Connection": [
            {
                "protocol": "http", "address": "192.168.80.10", "port": 32400,
                "local": "1", "relay": "0",
            },
            {
                "protocol": "http", "address": "203.0.113.5", "port": 32400,
                "local": "0", "relay": "0",
            },
        ],
    },
    {
        "name": "Garage",
        "product": "Plex Media Server",
        "productVersion": "1.40.5.8897",
        "clientIdentifier": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "provides": "server",
        "Connection": [
            {
                "protocol": "http", "address": "192.168.1.50", "port": 32400,
                "local": "0", "relay": "0",
            },
        ],
    },
    {
        "name": "Roku TV",
        "provides": "client,player",
        "Connection": [{"protocol": "http", "address": "192.168.80.99", "port": 8324}],
    },
]


class FakeSocket:
    """Records sends and replays queued datagrams, then raises socket.timeout."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def settimeout(self, value):
        pass

    def sendto(self, payload, target):
        self.sent.append((payload, target))

    def recvfrom(self, bufsize):
        if not self.replies:
            raise socket.timeout("no more datagrams")
        return self.replies.pop(0)

    def close(self):
        pass


def _run(replies, timeout=1.0, monkeypatch=None):
    monkeypatch.setattr(
        plex_discovery, "_open_discovery_socket", lambda: FakeSocket(replies)
    )
    return discover_plex_servers(timeout=timeout)


def test_parse_gdm() -> None:
    server = plex_discovery._parse_response(GDM_REPLY, ("192.168.1.5", 32414))
    assert server is not None
    assert server.name == "Living Room"
    assert server.host == "192.168.1.5"
    assert server.port == 32400
    assert server.version == "1.43.3.10828"
    assert server.machine_identifier == "3309a4b35976865b17593c74cb3f5b447c520cbf"
    assert server.url == "http://192.168.1.5:32400"


def test_parse_ssdp() -> None:
    server = plex_discovery._parse_response(SSDP_REPLY, ("192.168.1.7", 1900))
    assert server is not None
    assert server.host == "192.168.1.7"
    assert server.port == 32400
    assert server.version == "1.40.5.8897"
    # SSDP does not advertise a friendly name or machine id.
    assert server.name == "192.168.1.7"
    assert server.machine_identifier is None


def test_parse_ignores_requests_and_non_200() -> None:
    request = "M-SEARCH * HTTP/1.1\r\nST: urn:plex-com:service:pms:1\r\n\r\n".encode()
    assert plex_discovery._parse_response(request, ("1.2.3.4", 5)) is None
    not_ok = "HTTP/1.1 404 Not Found\r\n\r\n".encode()
    assert plex_discovery._parse_response(not_ok, ("1.2.3.4", 5)) is None


def test_discover_empty_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run([], monkeypatch=monkeypatch) == []


def test_discover_returns_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [
        (GDM_REPLY, ("192.168.1.5", 32400)),
        (GDM_REPLY, ("192.168.1.5", 32400)),  # duplicate — deduped
        (SSDP_REPLY, ("192.168.1.7", 1900)),
    ]
    servers = _run(replies, monkeypatch=monkeypatch)
    assert len(servers) == 2
    assert servers[0].host == "192.168.1.5"
    assert servers[1].host == "192.168.1.7"


def test_discover_sends_both_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = FakeSocket([])
    monkeypatch.setattr(plex_discovery, "_open_discovery_socket", lambda: sock)
    discover_plex_servers(timeout=0.05)
    targets = {target for _, target in sock.sent}
    assert ("239.0.0.250", 32414) in targets
    assert ("239.255.255.250", 1900) in targets


# ---------------------------------------------------------------- account


def test_account_discovery_parses_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plex_discovery.httpx, "get",
        lambda *a, **k: httpx.Response(
            200, json=ACCOUNT_RESOURCES,
            request=httpx.Request("GET", plex_discovery.PLEX_TV_RESOURCES_URL),
        ),
    )
    servers = plex_discovery.discover_plex_account_servers("tok")
    assert [s.name for s in servers] == ["Caladan", "Garage"]
    caladan = servers[0]
    assert caladan.host == "192.168.80.10"  # prefers local=1 connection
    assert caladan.port == 32400
    assert caladan.version == "1.43.3.10828"
    assert caladan.machine_identifier == "3309a4b35976865b17593c74cb3f5b447c520cbf"
    assert servers[1].host == "192.168.1.50"


def test_account_discovery_no_token_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(
        plex_discovery.httpx, "get",
        lambda *a, **k: called.append(True) or httpx.Response(200, json=[]),
    )
    assert plex_discovery.discover_plex_account_servers("") == []
    assert called == []


def test_account_discovery_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(plex_discovery.httpx, "get", _raise)
    assert plex_discovery.discover_plex_account_servers("tok") == []


def test_discover_merges_local_and_account(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [(GDM_REPLY, ("192.168.80.10", 32414))]
    monkeypatch.setattr(
        plex_discovery, "_open_discovery_socket", lambda: FakeSocket(replies)
    )
    monkeypatch.setattr(
        plex_discovery.httpx, "get",
        lambda *a, **k: httpx.Response(
            200, json=ACCOUNT_RESOURCES,
            request=httpx.Request("GET", plex_discovery.PLEX_TV_RESOURCES_URL),
        ),
    )
    servers = discover_plex_servers(timeout=1.0, token="tok")
    # Caladan found locally (GDM) and via account — deduped to one; Garage added.
    assert [s.host for s in servers] == ["192.168.1.50", "192.168.80.10"]
