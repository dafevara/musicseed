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
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel

GDM_GROUP = ("239.0.0.250", 32414)
SSDP_GROUP = ("239.255.255.250", 1900)

#: Reachability probe used by ``verify_servers``: ``/identity`` is public on every
#: Plex Media Server, so it answers without a token and cheaply.
IDENTITY_PATH = "/identity"
IDENTITY_PROBE_TIMEOUT = 2.5
_PROBE_WORKERS = 8

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
    """One Plex server discovered on the local network or the Plex account.

    A Plex server advertises several connections, and which of them work
    depends on where MusicSeed runs: a server on another LAN reports its own
    192.168.x addresses, which are unreachable from here, alongside the one
    address that does work (a VPN/Tailscale address, say). ``reachable`` is the
    result of probing the connection (``None`` when it was not probed), so a
    picker can prefer addresses that actually answer instead of guessing from
    Plex's ``local`` flag.
    """

    model_config = {"frozen": True}

    name: str
    host: str
    port: int
    product: str = "Plex Media Server"
    version: str | None = None
    machine_identifier: str | None = None
    scheme: str = "http"
    reachable: bool | None = None

    @property
    def url(self) -> str:
        """The server's base URL (``scheme://host:port``)."""
        return f"{self.scheme}://{self.host}:{self.port}"


def _probe_reachable(server: DiscoveredPlexServer, timeout: float) -> bool:
    """True when the server answers a plain ``/identity`` request."""
    try:
        resp = httpx.get(f"{server.url}{IDENTITY_PATH}", timeout=timeout)
    except httpx.HTTPError:
        return False
    return resp.status_code < 500


def verify_servers(
    servers: list[DiscoveredPlexServer],
    *,
    timeout: float = IDENTITY_PROBE_TIMEOUT,
) -> list[DiscoveredPlexServer]:
    """Probe every candidate connection and sort answering ones first.

    Probes run in parallel, so the total wait is bounded by ``timeout`` and not
    by the number of advertised addresses (Plex lists several per server). The
    order within each group is preserved, and unreachable entries are kept —
    the picker needs to show them (as unreachable) rather than hide the server.

    Args:
        servers: candidate connections, typically one per advertised address.
        timeout: per-probe timeout in seconds.

    Returns:
        The same entries with ``reachable`` set, reachable first.
    """
    if not servers:
        return []
    with ThreadPoolExecutor(max_workers=min(_PROBE_WORKERS, len(servers))) as pool:
        results = list(pool.map(lambda s: _probe_reachable(s, timeout), servers))
    probed = [
        server.model_copy(update={"reachable": ok})
        for server, ok in zip(servers, results)
    ]
    # sorted() is stable: each group keeps its discovery order.
    return sorted(probed, key=lambda s: {True: 0, None: 1, False: 2}[s.reachable])


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


def _is_docker_bridge(address: str) -> bool:
    """True for Docker's default bridge allocation (172.16.0.0/12)."""
    octets = address.split(".")
    if len(octets) != 4 or octets[0] != "172" or not octets[1].isdigit():
        return False
    return 16 <= int(octets[1]) <= 31


def _is_network_junk(address: str) -> bool:
    """True for IPv4 network/broadcast addresses (last octet 0 or 255)."""
    octets = address.split(".")
    return len(octets) == 4 and octets[3].isdigit() and int(octets[3]) in (0, 255)


def _connection_rank(conn: ElementTree.Element) -> int:
    """Plex's own connection preference, used only as an ordering hint."""
    address = (conn.get("address") or "").strip()
    local = str(conn.get("local")) == "1"
    if local and not _is_network_junk(address) and not _is_docker_bridge(address):
        return 0
    if local:
        return 1
    return 2


def _account_server_entries(device: ElementTree.Element) -> list[DiscoveredPlexServer]:
    """Build one entry per usable connection of a single account server.

    Every usable connection is returned, ordered by Plex's preference — not just
    the preferred one. Plex's ``local`` flag describes the *server's* view of its
    own interfaces, so the preferred address is frequently unreachable from the
    machine running MusicSeed (a remote server reports its LAN addresses).
    Callers that need the truth probe the addresses (:func:`verify_servers`)
    instead of trusting the ranking.

    Relay connections and addresses that cannot be a host (network/broadcast) or
    that look like Docker's bridge range are still dropped.
    """
    name = device.get("name") or ""
    product = device.get("product") or "Plex Media Server"
    version = device.get("productVersion")
    machine_id = device.get("clientIdentifier")

    connections = [
        c
        for c in device.findall("Connection")
        if str(c.get("relay")) != "1"
        and (c.get("address") or "").strip()
        and not _is_network_junk((c.get("address") or "").strip())
        and not _is_docker_bridge((c.get("address") or "").strip())
    ]

    entries: list[DiscoveredPlexServer] = []
    for conn in sorted(connections, key=_connection_rank):
        address = (conn.get("address") or "").strip()
        try:
            port = int(conn.get("port") or 32400)
        except (TypeError, ValueError):
            port = 32400
        entries.append(
            DiscoveredPlexServer(
                name=name or address,
                host=address,
                port=port,
                product=product,
                version=version,
                machine_identifier=machine_id,
                scheme=conn.get("protocol") or "http",
            )
        )
    return entries


def discover_plex_account_servers(
    token: str, timeout: float = 5.0, *, verify: bool = False
) -> list[DiscoveredPlexServer]:
    """Discover servers linked to the Plex account via ``plex.tv/api/resources``.

    Requires a Plex token and internet access. Returns an empty list (never
    raises) when the token is missing or the call fails — e.g. offline,
    invalid token, or no servers on the account.

    Args:
        token: Plex account token used to authenticate against plex.tv.
        timeout: HTTP timeout in seconds for the plex.tv request.
        verify: also probe each advertised address and set ``reachable``.

    Returns:
        One entry per best-ranked connection of each account server.
    """
    if not token:
        return []
    try:
        resp = httpx.get(
            PLEX_TV_RESOURCES_URL,
            headers={"X-Plex-Token": token, "Accept": "application/json"},
            timeout=timeout,
        )
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    # plex.tv returns XML here even when JSON is requested — parse the XML.
    try:
        root = ElementTree.fromstring(resp.text)
    except ElementTree.ParseError:
        return []

    servers: list[DiscoveredPlexServer] = []
    for device in root.findall("Device"):
        if "server" not in (device.get("provides") or "").split(","):
            continue
        servers.extend(_account_server_entries(device))
    return verify_servers(servers) if verify else servers


def discover_plex_servers(
    timeout: float = 3.0, token: str | None = None, *, verify: bool = False
) -> list[DiscoveredPlexServer]:
    """Discover Plex servers — local subnet via GDM/SSDP, plus the account.

    With ``token`` set, also queries ``plex.tv/api/resources`` so servers on
    other subnets (invisible to multicast) are included. Results are deduplicated
    by address. Returns an empty list when nothing responds; never raises.

    Args:
        timeout: seconds to listen for local multicast replies; also the
            plex.tv request timeout when ``token`` is set.
        token: optional Plex account token enabling cross-subnet discovery.
        verify: also probe each address so callers can tell which connections
            actually work from this machine (see :func:`verify_servers`).

    Returns:
        Discovered servers sorted by ``(host, port, name)``, or with reachable
        entries first when ``verify`` is set.
    """
    servers: dict[tuple[str, str, int], DiscoveredPlexServer] = {}
    _discover_local_servers(servers, timeout)
    if token:
        for server in discover_plex_account_servers(token, timeout=timeout):
            servers.setdefault(_server_key(server), server)

    found = sorted(servers.values(), key=lambda s: (s.host, s.port, s.name))
    return verify_servers(found) if verify else found
