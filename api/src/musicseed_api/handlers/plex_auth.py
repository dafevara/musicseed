"""Plex sign-in orchestration for the JSON API.

A thin layer over core's ``services.plex_link``: create a plex.tv PIN, poll it
until the user approves it, report the linked account, and unlink. Handlers
return Pydantic models and never carry a Plex token in a response body.
"""

from __future__ import annotations

from urllib.parse import urlparse

from musicseed.exceptions import ConfigurationError
from musicseed.logging_config import get_logger
from musicseed.services.plex_link import (
    Handoff,
    PlexAccountInfo,
    PlexLinkResult,
    PlexLinkStart,
    get_plex_account,
    poll_plex_link,
    start_plex_link,
    unlink_plex,
)

logger = get_logger("api.plex_auth")

_HANDOFFS: tuple[str, ...] = ("forward", "link")


def _handoff(value: str) -> Handoff:
    if value not in _HANDOFFS:
        raise ConfigurationError(
            f"Unknown Plex sign-in hand-off {value!r}. "
            f"Expected one of: {', '.join(_HANDOFFS)}."
        )
    return value  # type: ignore[return-value]


def _safe_forward_url(forward_url: str, origin: str | None) -> str:
    """Reject a return URL plex.tv should not be asked to redirect to.

    ``forward_url`` comes from the browser, so it is validated as an absolute
    http(s) URL that matches the origin the request came from. This keeps the
    local API from becoming an open redirect.
    """
    if not forward_url.strip():
        return ""
    parsed = urlparse(forward_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigurationError("forward_url must be an absolute http(s) URL.")
    if origin:
        expected = urlparse(origin).netloc
        if expected and parsed.netloc != expected:
            raise ConfigurationError(
                "forward_url must point at this MusicSeed instance."
            )
    return forward_url


def start_link(
    handoff: str = "forward", forward_url: str = "", origin: str | None = None
) -> PlexLinkStart:
    """Create a Plex sign-in PIN and return the URLs the user must approve."""
    return start_plex_link(
        handoff=_handoff(handoff),
        forward_url=_safe_forward_url(forward_url, origin),
    )


def poll_link(pin_id: int) -> PlexLinkResult:
    """Check one PIN; persists the token when the user has approved it."""
    return poll_plex_link(pin_id)


def read_account() -> PlexAccountInfo | None:
    """Return the linked Plex account, or ``None`` when not linked/verified."""
    return get_plex_account()


def clear_link() -> bool:
    """Forget the stored Plex token. Returns True when there was one."""
    return unlink_plex()
