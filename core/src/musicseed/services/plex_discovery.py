"""Plex server discovery — local network (GDM + SSDP) and account (plex.tv).

Two independent, read-only discovery paths feed one result list:

* **Local network** — GDM ("Good Day Mate") multicast on ``239.0.0.250:32414``
  with an SSDP fallback on ``239.255.255.250:1900``. Both use stdlib ``socket``
  only and find servers on the *same subnet* (multicast never crosses a
  router). GDM replies carry the friendly name, port, product, version, and
  machine identifier.
* **Account** — ``plex.tv/api/resources`` lists every server linked to the
  user's Plex account, including servers on *other subnets* that multicast
  cannot reach. Requires a Plex token and internet access.

Both paths are strictly read-only and never store or return a token.

This is a deliberately separate, opt-in probe — it is *not* folded into
``services.discovery.discover()``, which runs on frequent dashboard polls and
must stay cheap. The first-run wizard calls it once.
"""

from __future__ import annotations

import re
import socket
import time
from urllib.parse import urlparse

import httpx
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

PLEX_TV_RESOURCES_URL = "https://plex.tv/api/resources"

_SSDP_SERVER_VERSION = re.compile(r"Plex Media Server/([\d.]+)")


class DiscoveredPlexServer(BaseModel):
    """One Plex server discovered on the local network or the Plex account."""

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
        machine_identifier=(
            headers.get("machine-identifier") or headers.get("resource-identifier")
        ),
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
    if (
        "plex/media-server" in headers.get("content-type", "")
        or "machine-identifier" in headers
        or "resource-identifier" in headers
    ):
        return _parse_gdm(headers, addr)
    if "location" in headers or "st" in headers:
        return _parse_ssdp(headers, addr)
    return None


def _server_key(server: DiscoveredPlexServer) -> tuple[str, str, int]:
    """Identity used to deduplicate servers across discovery paths."""
    return (server.scheme, server.host, server.port)


def _discover_local_servers(
    servers: dict[tuple[str, str, int], DiscoveredPlexServer], timeout: float
) -> None:
    """Populate ``servers`` with same-subnet GDM/SSDP replies (in place)."""
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
            servers.setdefault(_server_key(server), server)
    finally:
        sock.close()


def _pick_connection(connections: list[dict]) -> dict | None:
    """Choose the best reachable address for a server (local, then non-relay)."""
    if not connections:
        return None
    for conn in connections:
        if str(conn.get("local")) == "1" and str(conn.get("relay")) != "1":
            return conn
    for conn in connections:
        if str(conn.get("relay")) != "1":
            return conn
    return connections[0]


def discover_plex_account_servers(
    token: str, timeout: float = 5.0
) -> list[DiscoveredPlexServer]:
    """Discover servers linked to the Plex account via ``plex.tv/api/resources``.

    Requires a Plex token and internet access. Returns an empty list (never
    raises) when the token is missing or the call fails — e.g. offline,
    invalid token, or no servers on the account.
    """
    if not token:
        return []
    try:
        resp = httpx.get(
            PLEX_TV_RESOURCES_URL,
            headers={"X-Plex-Token": token, "Accept": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        devices = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    servers: list[DiscoveredPlexServer] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        if "server" not in (device.get("provides") or "").split(","):
            continue
        conn = _pick_connection(device.get("Connection") or [])
        if conn is None:
            continue
        address = str(conn.get("address") or "").strip()
        if not address:
            continue
        try:
            port = int(conn.get("port") or 32400)
        except (TypeError, ValueError):
            port = 32400
        servers.append(
            DiscoveredPlexServer(
                name=device.get("name") or address,
                host=address,
                port=port,
                product=device.get("product") or "Plex Media Server",
                version=device.get("productVersion"),
                machine_identifier=device.get("clientIdentifier"),
                scheme=conn.get("protocol") or "http",
            )
        )
    return servers


def discover_plex_servers(
    timeout: float = 3.0, token: str | None = None
) -> list[DiscoveredPlexServer]:
    """Discover Plex servers — local subnet via GDM/SSDP, plus the account.

    With ``token`` set, also queries ``plex.tv/api/resources`` so servers on
    other subnets (invisible to multicast) are included. Results are deduplicated
    by address. Returns an empty list when nothing responds; never raises.
    """
    servers: dict[tuple[str, str, int], DiscoveredPlexServer] = {}
    _discover_local_servers(servers, timeout)
    if token:
        for server in discover_plex_account_servers(token, timeout=timeout):
            servers.setdefault(_server_key(server), server)

    return sorted(
        servers.values(), key=lambda s: (s.host, s.port, s.name)
    )
