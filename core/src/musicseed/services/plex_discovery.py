"""Local-network Plex server discovery (GDM + SSDP).

Passive, read-only discovery of Plex Media Servers on the local network. Two
probes are used, both stdlib ``socket`` only (no zeroconf/upnpclient):

* **GDM** ("Good Day Mate") — Plex's own multicast protocol on
  ``239.0.0.250:32414``. A single ``M-SEARCH`` datagram makes every server on
  the subnet reply with its friendly name, port, product, version, and machine
  identifier.
* **SSDP** fallback — a UPnP ``M-SEARCH`` on ``239.255.255.250:1900`` for
  ``urn:plex-com:service:pms:1``. Responses carry ``LOCATION`` (host/port) and
  ``SERVER`` (version); the friendly name is not advertised, so it falls back
  to the host.

Both probes are strictly read-only: they send one discovery datagram and parse
unicast replies. No token is read, stored, or returned.

This is a deliberately separate, opt-in probe — it is *not* folded into
``services.discovery.discover()``, which runs on frequent dashboard polls and
must stay cheap. The first-run wizard calls it once.
"""

from __future__ import annotations

import re
import socket
import time
from urllib.parse import urlparse

from pydantic import BaseModel

GDM_GROUP = ("239.0.0.250", 32414)
SSDP_GROUP = ("239.255.255.250", 1900)

GDM_REQUEST = "M-SEARCH * HTTP/1.1\r\n\r\n"
SSDP_REQUEST = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_GROUP[0]}:{SSDP_GROUP[1]}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: urn:plex-com:service:pms:1\r\n"
    "\r\n"
)

_SSDP_SERVER_VERSION = re.compile(r"Plex Media Server/([\d.]+)")


class DiscoveredPlexServer(BaseModel):
    """One Plex server discovered on the local network."""

    model_config = {"frozen": True}

    name: str
    host: str
    port: int
    product: str = "Plex Media Server"
    version: str | None = None
    machine_identifier: str | None = None
    scheme: str = "http"

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def _open_discovery_socket() -> socket.socket:
    """Create a reusable UDP socket bound to an ephemeral port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    except OSError:
        pass
    sock.bind(("", 0))
    return sock


def _parse_headers(raw: str) -> tuple[str | None, dict[str, str]]:
    """Split an HTTP-like datagram into (status_line, lowercased_headers)."""
    lines = raw.replace("\r\n", "\n").split("\n")
    if not lines:
        return None, {}
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    return lines[0], headers


def _parse_gdm(headers: dict[str, str], addr: tuple[str, int]) -> DiscoveredPlexServer:
    port = headers.get("port", "32400")
    try:
        port_num = int(port)
    except (TypeError, ValueError):
        port_num = 32400
    return DiscoveredPlexServer(
        name=headers.get("name") or addr[0],
        host=addr[0],
        port=port_num,
        product=headers.get("product") or "Plex Media Server",
        version=headers.get("version"),
        machine_identifier=headers.get("machine-identifier"),
    )


def _parse_ssdp(headers: dict[str, str], addr: tuple[str, int]) -> DiscoveredPlexServer:
    host, port = addr[0], 32400
    location = headers.get("location")
    if location:
        parsed = urlparse(location)
        if parsed.hostname:
            host = parsed.hostname
        if parsed.port:
            port = parsed.port

    version = None
    match = _SSDP_SERVER_VERSION.search(headers.get("server") or "")
    if match:
        version = match.group(1)

    return DiscoveredPlexServer(
        name=host,
        host=host,
        port=port,
        version=version,
    )


def _parse_response(data: bytes, addr: tuple[str, int]) -> DiscoveredPlexServer | None:
    try:
        text = data.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        return None
    status, headers = _parse_headers(text)
    if not status or "200" not in status:
        return None
    if "machine-identifier" in headers:
        return _parse_gdm(headers, addr)
    if "location" in headers or "st" in headers:
        return _parse_ssdp(headers, addr)
    return None


def discover_plex_servers(timeout: float = 3.0) -> list[DiscoveredPlexServer]:
    """Discover Plex servers on the local network.

    Sends one GDM probe and one SSDP probe, then listens for replies until
    ``timeout`` elapses. Returns an empty list when nothing responds; never
    raises on network errors.
    """
    servers: dict[tuple[str, str, int], DiscoveredPlexServer] = {}
    sock = _open_discovery_socket()
    try:
        for target, payload in ((GDM_GROUP, GDM_REQUEST), (SSDP_GROUP, SSDP_REQUEST)):
            try:
                sock.sendto(payload.encode("utf-8"), target)
            except OSError:
                pass

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(max(remaining, 0.05))
            try:
                data, addr = sock.recvfrom(8192)
            except socket.timeout:
                break
            server = _parse_response(data, addr)
            if server is None:
                continue
            key = (server.machine_identifier or "", server.host, server.port)
            servers.setdefault(key, server)
    finally:
        sock.close()

    return sorted(
        servers.values(), key=lambda s: (s.host, s.port, s.name)
    )
