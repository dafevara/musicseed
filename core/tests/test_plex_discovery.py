"""Tests for services.plex_discovery — no real multicast or network involved."""

import socket

import pytest
from musicseed.services import plex_discovery
from musicseed.services.plex_discovery import discover_plex_servers

GDM_REPLY = (
    "HTTP/1.0 200 OK\r\n"
    "Name: Living Room\r\n"
    "Port: 32400\r\n"
    "Product: Plex Media Server\r\n"
    "Version: 1.41.0.9000\r\n"
    "Machine-Identifier: deadbeefcafe\r\n"
    "Content-Type: plex/media-server\r\n"
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
    server = plex_discovery._parse_response(GDM_REPLY, ("192.168.1.5", 32400))
    assert server is not None
    assert server.name == "Living Room"
    assert server.host == "192.168.1.5"
    assert server.port == 32400
    assert server.version == "1.41.0.9000"
    assert server.machine_identifier == "deadbeefcafe"
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
