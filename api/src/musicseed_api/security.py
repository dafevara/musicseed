"""Browser-facing security middleware for the MusicSeed JSON API.

MusicSeed is a local-first, single-user tool that intentionally runs without
login on a trusted home LAN. That trust boundary still needs browser
protections, which are layered here rather than relying on any single check:

* **Host allowlist** — reject requests whose ``Host`` header names an
  unexpected hostname. This blocks DNS-rebinding and host-header injection
  against the local API. Loopback and private (home-LAN) addresses are allowed
  by default; ``security.allowed_hosts`` adds explicit names.

* **Origin check** — reject state-changing requests whose ``Origin``/``Referer``
  names a host that is neither the request's own host nor a trusted local/LAN
  address. This stops an unrelated website from driving MusicSeed's write
  endpoints directly.

* **CSRF token** — any state-changing request that carries a browser
  ``Origin``/``Referer`` must also present a valid ``X-MusicSeed-CSRF`` header
  obtained from ``GET /security/csrf``. A malicious website cannot read that
  token (no CORS is configured), so even a localhost-only attack is blocked.
  Non-browser clients (the CLI, MCP, curl) send no ``Origin`` and are exempt.

The three checks are complementary: the host allowlist rejects unexpected
hostnames, the origin check rejects unrelated websites, and the CSRF token
rejects any browser request that never fetched a token.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from musicseed.config import Config, get_config, save_config

CSRF_HEADER = "X-MusicSeed-CSRF"
CSRF_ENDPOINT = "/security/csrf"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_SCOPE = b"musicseed-csrf"


def _hostname(value: str) -> str:
    """Extract the host portion (no port, no brackets) from a Host header or URL."""
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        return value[1:end].lower() if end != -1 else value.lower()
    if value.count(":") == 1:
        value = value.rsplit(":", 1)[0]
    return value.lower().rstrip(".")


def _ip(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def is_trusted_network_host(hostname: str) -> bool:
    """Loopback, link-local, private/LAN, or CGNAT/VPN — not globally routable.

    ``is_global`` is False for loopback, RFC1918 private, link-local, and
    CGNAT/Tailscale (100.64.0.0/10) addresses, so a MusicSeed instance hosted
    on a LAN or VPN address is reachable while a public hostname is not trusted
    without an explicit ``security.allowed_hosts`` entry.
    """
    hostname = _hostname(hostname)
    if hostname == "localhost":
        return True
    ip = _ip(hostname)
    if ip is None:
        return False
    return not ip.is_global


def host_allowed(host: str, allowed_hosts: list[str] | tuple[str, ...] | set[str]) -> bool:
    """Return whether ``host`` is loopback/private or explicitly allowlisted."""
    hostname = _hostname(host)
    if not hostname:
        return False
    if is_trusted_network_host(hostname):
        return True
    return hostname in {_hostname(h) for h in allowed_hosts}


def get_csrf_secret(config: Config | None = None) -> str:
    """Return the per-install CSRF secret, generating and persisting it once.

    The secret is written owner-only to the config file so the token survives
    an API restart. It is never returned to a client.
    """
    cfg = config if config is not None else get_config()
    if cfg.security.csrf_secret:
        return cfg.security.csrf_secret
    cfg.security.csrf_secret = secrets.token_urlsafe(32)
    save_config(cfg)
    return cfg.security.csrf_secret


def issue_csrf_token(secret: str) -> str:
    """Derive the CSRF token for this install (HMAC over a fixed scope)."""
    return hmac.new(secret.encode("utf-8"), _CSRF_SCOPE, hashlib.sha256).hexdigest()


def verify_csrf_token(secret: str, token: str) -> bool:
    """Constant-time check of a submitted CSRF token."""
    if not token:
        return False
    return hmac.compare_digest(issue_csrf_token(secret), token)


def _origin_host(request: Request) -> str:
    """Host of the request's Origin (preferred) or Referer, or "" when absent."""
    raw = request.headers.get("origin") or request.headers.get("referer")
    if not raw:
        return ""
    parsed = urlparse(raw)
    return _hostname(parsed.hostname or "")


def _origin_is_untrusted(origin_host: str, hostname: str, allowed_hosts) -> bool:
    """Reject an origin that is neither same-host nor a trusted local/LAN host."""
    if not origin_host:
        return False
    if origin_host == hostname:
        return False
    if is_trusted_network_host(origin_host):
        return False
    return origin_host not in {_hostname(h) for h in allowed_hosts}


async def security_filter(request: Request, call_next):
    """Validate Host, reject unrelated websites, and enforce CSRF on writes.

    Returns the downstream response on success, or a JSON 400/403 otherwise.
    """
    host_header = request.headers.get("host", "")
    hostname = _hostname(host_header)
    config = get_config()
    allowed = config.security.allowed_hosts

    if not host_allowed(host_header, allowed):
        return JSONResponse(
            status_code=400,
            content={"detail": f"Unexpected Host header: {host_header or '(missing)'}"},
        )

    # Bound request bodies before they are parsed, so an oversized form cannot
    # force unbounded work in the multipart/JSON layer.
    content_length = request.headers.get("content-length")
    if (
        content_length is not None
        and content_length.isdigit()
        and int(content_length) > config.limits.max_request_body_bytes
    ):
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body too large."},
        )

    if request.method in SAFE_METHODS:
        return await call_next(request)

    origin_host = _origin_host(request)
    if origin_host:
        if _origin_is_untrusted(origin_host, hostname, allowed):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-site request rejected."},
            )
        # A browser is driving this write: require the CSRF token it fetched.
        token = request.headers.get(CSRF_HEADER, "")
        if not verify_csrf_token(get_csrf_secret(config), token):
            return JSONResponse(
                status_code=403,
                content={"detail": "Missing or invalid CSRF token."},
            )

    return await call_next(request)
