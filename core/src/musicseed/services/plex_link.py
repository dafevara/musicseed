"""Plex account linking — sign in with Plex instead of pasting a token.

Implements Plex's documented PIN ("device linking") flow, the same one
``app.plex.tv``, Plexamp, and other third-party apps use. The user never types
a token: MusicSeed creates a time-limited PIN, the user approves it on Plex's
own sign-in page, and MusicSeed exchanges the claimed PIN for the account's
access token.

Two hand-offs are supported, sharing all other logic:

* ``"forward"`` — strong PIN (long code, 30 min). The user's browser is sent to
  the Auth App URL (``app.plex.tv/auth``) and returns to ``forward_url`` when
  it is provided. Best for the web wizard.
* ``"link"`` — short PIN (4 characters, 15 min). The user types the code at
  ``plex.tv/link`` from any device. Best for the CLI and headless installs.

Surface-agnostic and side-effect-visible only through the documented
credentials it persists: the retrieved token (plus the Plex server URL when
one can be derived) is written to the local config file, which is the single
place every surface — web UI, CLI, and MCP — reads its Plex credentials from.

Design notes:

* ``plex.client_identifier`` is generated once and persisted, then reused
  forever. Rotating it would create duplicate entries in the user's Plex
  "Authorized Devices" list and invalidate in-flight PINs.
* A token is only persisted after ``GET /api/v2/user`` confirms it, so a
  half-linked state is never written.
* Neither the token nor the PIN is logged.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field

from musicseed import __version__
from musicseed.clients.plex import PlexClient
from musicseed.config import (
    Config,
    PlexConfig,
    get_config,
    reload_config,
    save_config,
    set_config,
    url_is_remote_cleartext,
)
from musicseed.exceptions import ConfigurationError, MusicSeedError
from musicseed.logging_config import get_logger
from musicseed.services.plex_discovery import (
    DiscoveredPlexServer,
    discover_plex_account_servers,
)

logger = get_logger("plex_link")

PLEX_TV_PINS_URL = "https://plex.tv/api/v2/pins"
PLEX_TV_USER_URL = "https://plex.tv/api/v2/user"
PLEX_AUTH_APP_URL = "https://app.plex.tv/auth"
PLEX_LINK_URL = "https://plex.tv/link"

PRODUCT_NAME = "MusicSeed"

DEFAULT_TIMEOUT = 15.0
"""Seconds allowed for a single plex.tv request."""

#: PIN lifetime reported by plex.tv; used only as a client-side poll ceiling.
_FALLBACK_EXPIRES_IN = {"forward": 1800, "link": 900}

Handoff = Literal["forward", "link"]

UNLINK_GUIDANCE = (
    "To revoke it completely, remove MusicSeed from your Plex account's "
    "Authorized Devices page (https://app.plex.tv/desktop/#!/settings/devices)."
)

PLEX_LINK_GUIDANCE = (
    "Plex isn't linked yet. Open the MusicSeed web interface and choose "
    "\"Sign in with Plex\" on the setup or settings page, or run "
    "\"musicseed-cli plex-login\" in a terminal. MCP tools cannot sign in "
    "interactively — they use the credentials saved by one of those two."
)


class PlexLinkError(MusicSeedError):
    """plex.tv was unreachable or returned an unexpected response."""


class PlexLinkStart(BaseModel):
    """A created PIN the user still needs to approve on Plex's sign-in page."""

    model_config = {"frozen": True}

    pin_id: int
    code: str
    handoff: Handoff
    #: URL for the ``forward`` hand-off (``app.plex.tv/auth``), code included.
    auth_url: str
    #: Short link where a ``link`` hand-off code is typed.
    link_url: str
    expires_in: int


class PlexAccountInfo(BaseModel):
    """The Plex account a token belongs to (never includes the token)."""

    model_config = {"frozen": True}

    id: int | None = None
    username: str | None = None
    title: str | None = None
    email: str | None = None


class PlexLinkResult(BaseModel):
    """Outcome of one poll: linked, still waiting, or expired."""

    model_config = {"frozen": True}

    linked: bool
    pending: bool = False
    expired: bool = False
    #: True when this poll wrote the token to the local config file.
    token_saved: bool = False
    #: Plex server URL derived from the account, when config had none.
    url_saved: str | None = None
    account: PlexAccountInfo | None = None
    servers: list[DiscoveredPlexServer] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# plex.tv transport
# ---------------------------------------------------------------------------


def _headers(client_identifier: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Plex-Client-Identifier": client_identifier,
        "X-Plex-Product": PRODUCT_NAME,
        "X-Plex-Version": __version__,
        "X-Plex-Platform": "Python",
    }


def _client_identifier(cfg: Config) -> str:
    """Return the persisted client identifier, generating and saving it once."""
    if cfg.plex.client_identifier:
        return cfg.plex.client_identifier
    cfg.plex.client_identifier = uuid.uuid4().hex
    logger.info("Generated a new Plex client identifier (stored in config)")
    persist_config(cfg)
    return cfg.plex.client_identifier


def _auth_app_url(client_identifier: str, code: str, forward_url: str) -> str:
    """Build the ``app.plex.tv/auth`` URL (parameters live in the URL fragment)."""
    params: dict[str, str] = {
        "clientID": client_identifier,
        "code": code,
        "context[device][product]": PRODUCT_NAME,
        "context[device][version]": __version__,
    }
    if forward_url:
        params["forwardUrl"] = forward_url
    return f"{PLEX_AUTH_APP_URL}#?{urlencode(params)}"


# ---------------------------------------------------------------------------
# config persistence
# ---------------------------------------------------------------------------


def persist_config(cfg: Config) -> Config:
    """Save ``cfg`` and refresh both the process config and the runtime context.

    Mirrors the API handler's config writers: the saved file is what the CLI
    and MCP processes read, and the in-process swap keeps the current surface
    consistent without a restart.
    """
    from musicseed.context import MusicSeedContext, set_context
    from musicseed.services.jobs import configuration_change

    with configuration_change():
        save_config(cfg)
        set_config(cfg)
        set_context(MusicSeedContext(cfg))
    return cfg


def require_plex_token(config: Config | None = None) -> str:
    """Return the configured Plex token or raise an actionable error.

    Every Plex write path funnels through here so the missing-credentials
    message names the two real fixes (web sign-in or ``plex-login``) instead of
    leaking a raw config field name to end users.

    Raises:
        ConfigurationError: when no token is configured, even after re-reading
            the config file from disk.
    """
    cfg = config or get_config()
    if cfg.plex.token:
        return cfg.plex.token
    from musicseed.context import get_bound_context

    # An operation bound to an explicit context gets that config or nothing;
    # only the process-default path may re-read the file behind the caller.
    if get_bound_context() is None:
        fresh = reload_config()
        if fresh.plex.token:
            return fresh.plex.token
    raise ConfigurationError(PLEX_LINK_GUIDANCE)


def plex_client(
    config: Config | None = None, *, timeout: float = 15.0
) -> PlexClient:
    """Build a Plex client for the configured server, guarding cleartext remote.

    The stored Plex token travels with every Plex request. Sending it over
    plain ``http://`` to a remote (non-local) host is refused unless
    ``plex.allow_cleartext_remote`` is set, making cleartext remote a
    deliberate choice. Local and home-LAN HTTP remain supported, and https://
    keeps httpx's certificate verification enabled.

    Raises:
        ConfigurationError: when Plex is not linked, or the configured URL is
            remote cleartext without the explicit opt-in flag.
    """
    cfg = config or get_config()
    token = require_plex_token(cfg)
    if url_is_remote_cleartext(cfg.plex.url) and not cfg.plex.allow_cleartext_remote:
        raise ConfigurationError(
            "The configured Plex server uses plain http:// to a remote address, "
            "which would send your Plex token in cleartext over the network. "
            "Use https:// (or a VPN/tunnel), or set "
            "plex.allow_cleartext_remote: true to opt in deliberately."
        )
    return PlexClient(base_url=cfg.plex.url, token=token, timeout=timeout)


# ---------------------------------------------------------------------------
# linking
# ---------------------------------------------------------------------------


def start_plex_link(
    *,
    handoff: Handoff = "forward",
    forward_url: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    config: Config | None = None,
) -> PlexLinkStart:
    """Create a PIN and return the URLs the user needs to approve it.

    Args:
        handoff: ``"forward"`` for the browser ``app.plex.tv/auth`` flow (strong
            PIN), ``"link"`` for typing a short code at ``plex.tv/link``.
        forward_url: absolute URL the browser returns to after signing in;
            only used by the ``forward`` hand-off.
        timeout: seconds allowed for the plex.tv request.
        config: explicit config; defaults to the process config.

    Returns:
        The created PIN with both hand-off URLs.

    Raises:
        PlexLinkError: when plex.tv is unreachable or answers unexpectedly.
    """
    cfg = config or get_config()
    client_identifier = _client_identifier(cfg)
    strong = handoff == "forward"
    params = {"strong": "true"} if strong else {}
    try:
        resp = httpx.post(
            PLEX_TV_PINS_URL,
            params=params,
            headers=_headers(client_identifier),
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as e:
        raise PlexLinkError(
            "Could not reach plex.tv to start sign-in. Check this machine's "
            "internet connection, then try again (offline installs can still "
            "paste a token manually)."
        ) from e
    except ValueError as e:
        raise PlexLinkError("plex.tv returned an unexpected response.") from e

    pin_id = payload.get("id")
    code = payload.get("code") or ""
    if not pin_id or not code:
        raise PlexLinkError("plex.tv did not return a usable sign-in code.")
    expires_in = payload.get("expiresIn") or _FALLBACK_EXPIRES_IN[handoff]
    logger.info("Started Plex link (handoff=%s, expires_in=%ss)", handoff, expires_in)
    return PlexLinkStart(
        pin_id=int(pin_id),
        code=str(code),
        handoff=handoff,
        auth_url=_auth_app_url(client_identifier, str(code), forward_url),
        link_url=PLEX_LINK_URL,
        expires_in=int(expires_in),
    )


def poll_plex_link(
    pin_id: int,
    *,
    save: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    config: Config | None = None,
) -> PlexLinkResult:
    """Check a PIN once; when claimed, validate and persist the account token.

    Args:
        pin_id: the ``pin_id`` from :func:`start_plex_link`.
        save: write the retrieved token (and a derived server URL) to the local
            config file. ``False`` validates the link without persisting.
        timeout: seconds allowed for the plex.tv request.
        config: explicit config; defaults to the process config.

    Returns:
        ``linked=True`` with the account and its servers, ``pending=True`` while
        the user has not approved the PIN yet, or ``expired=True`` once plex.tv
        no longer accepts it.

    Raises:
        PlexLinkError: when plex.tv is unreachable or the token is rejected.
    """
    cfg = config or get_config()
    client_identifier = _client_identifier(cfg)
    try:
        resp = httpx.get(
            f"{PLEX_TV_PINS_URL}/{pin_id}",
            headers=_headers(client_identifier),
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise PlexLinkError("Could not reach plex.tv to finish sign-in.") from e
    if resp.status_code == 404:
        return PlexLinkResult(linked=False, expired=True)
    if resp.status_code == 429 or resp.status_code >= 500:
        # Transient plex.tv trouble: keep the PIN alive instead of dropping it,
        # so a brief outage does not force the user to start over.
        logger.warning("plex.tv returned HTTP %s while polling; retrying", resp.status_code)
        return PlexLinkResult(linked=False, pending=True)
    try:
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPStatusError as e:
        raise PlexLinkError(
            f"plex.tv rejected the sign-in request (HTTP {e.response.status_code})."
        ) from e
    except ValueError as e:
        raise PlexLinkError("plex.tv returned an unexpected response.") from e

    token = payload.get("authToken")
    if not token:
        return PlexLinkResult(linked=False, pending=True)

    account = fetch_account(token, timeout=timeout)
    if account is None:
        # Claimed, but the resulting token is unusable — never persist it.
        raise PlexLinkError(
            "Plex accepted the sign-in but the resulting token was rejected. "
            "Try again, or paste a token manually."
        )

    servers = discover_plex_account_servers(token, timeout=timeout, verify=True)
    url_saved: str | None = None
    token_saved = False
    if save:
        token_saved, url_saved = _save_credentials(cfg, token, servers)
        logger.info(
            "Plex account linked (%d servers found, token_saved=%s, url_saved=%s)",
            len(servers),
            token_saved,
            url_saved,
        )
    else:
        logger.info("Plex account verified without saving (save=False)")
    return PlexLinkResult(
        linked=True,
        token_saved=token_saved,
        url_saved=url_saved,
        account=account,
        servers=servers,
    )


def wait_for_plex_link(
    pin_id: int,
    *,
    timeout: float | None = None,
    interval: float = 2.0,
    sleep=time.sleep,
) -> PlexLinkResult:
    """Poll ``poll_plex_link`` until the PIN is claimed, expires, or times out.

    Args:
        pin_id: the ``pin_id`` from :func:`start_plex_link`.
        timeout: overall seconds to wait; defaults to 30 minutes.
        interval: seconds between polls.
        sleep: injected sleeper (tests pass a no-op).

    Returns:
        The first non-pending result, or a pending result when ``timeout`` runs
        out first.
    """
    deadline = time.monotonic() + (timeout if timeout is not None else 1800.0)
    while True:
        result = poll_plex_link(pin_id)
        if result.linked or result.expired:
            return result
        if time.monotonic() >= deadline:
            return result
        sleep(interval)


def _save_credentials(
    cfg: Config, token: str, servers: list[DiscoveredPlexServer]
) -> tuple[bool, str | None]:
    """Persist the token, and a server URL when one can be picked safely.

    Returns:
        ``(saved_anything, url_derived)`` where ``url_derived`` is only set when
        this call actually replaced the configured Plex server URL.
    """
    updated = cfg.model_copy(deep=True)
    saved = False
    url_saved: str | None = None
    if updated.plex.token != token:
        updated.plex.token = token
        saved = True
    # An explicit server choice wins; only an unset URL (or the shipped
    # localhost default) is replaced, and only when the account has one server.
    candidate = _candidate_url(servers)
    if candidate and updated.plex.url.strip() in ("", PlexConfig().url):
        updated.plex.url = candidate
        saved = True
        url_saved = candidate
    if saved:
        persist_config(updated)
    return saved, url_saved


def _candidate_url(servers: list[DiscoveredPlexServer]) -> str | None:
    """A server URL worth saving automatically, or ``None`` when unproven/ambiguous.

    A Plex server advertises several addresses and most of them may be
    unreachable from this machine (a remote server reports its own LAN
    addresses). Only an address that actually answered is saved, so a fresh
    sign-in never leaves MusicSeed pointed at a dead host. With more than one
    server on the account, guessing would silently pick the wrong box — the
    wizard's server picker is the right place to choose.
    """
    identities = {server.machine_identifier or server.name for server in servers}
    if len(identities) != 1:
        return None
    reachable = [server for server in servers if server.reachable]
    if not reachable:
        return None
    return _preferred_url(reachable[0])


def _preferred_url(server: DiscoveredPlexServer) -> str:
    if server.scheme in ("http", "https") and server.host and server.port:
        return f"{server.scheme}://{server.host}:{server.port}"
    return server.url


def fetch_account(
    token: str, *, timeout: float = DEFAULT_TIMEOUT
) -> PlexAccountInfo | None:
    """Validate ``token`` against plex.tv and return its account, or ``None``.

    Never raises for a rejected token: ``401`` means revoked or invalid, and a
    plex.tv outage returns ``None`` too. Callers treat ``None`` as "not
    verified" and say so rather than persisting anything.
    """
    cfg = get_config()
    client_identifier = cfg.plex.client_identifier or uuid.uuid4().hex
    if not token:
        return None
    try:
        resp = httpx.get(
            PLEX_TV_USER_URL,
            headers={**_headers(client_identifier), "X-Plex-Token": token},
            timeout=timeout,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    return PlexAccountInfo(
        id=payload.get("id"),
        username=payload.get("username"),
        title=payload.get("title"),
        email=payload.get("email"),
    )


def get_plex_account(
    token: str | None = None, *, timeout: float = DEFAULT_TIMEOUT
) -> PlexAccountInfo | None:
    """Return the account the configured (or given) token belongs to.

    Used to tell "linked" from "revoked or invalid token" without making a
    server request.
    """
    resolved = get_config().plex.token if token is None else token
    if not resolved:
        return None
    return fetch_account(resolved, timeout=timeout)


def unlink_plex(config: Config | None = None) -> bool:
    """Clear the stored Plex token. Returns True when something was cleared.

    The client identifier is kept so re-linking reuses the same Plex
    "Authorized Devices" entry.
    """
    cfg = config or get_config()
    if not cfg.plex.token:
        return False
    updated = cfg.model_copy(deep=True)
    updated.plex.token = ""
    persist_config(updated)
    logger.info("Cleared the stored Plex token")
    return True
