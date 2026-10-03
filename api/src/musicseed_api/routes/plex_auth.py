"""JSON endpoints for Plex account sign-in (no manual token required).

The browser never sees a Plex token: it starts a PIN, sends the user to Plex's
own sign-in page, and polls MusicSeed until the approved token has been written
to the local config file — where the CLI and MCP surfaces read it from.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from musicseed.logging_config import get_logger

from musicseed_api.handlers.plex_auth import (
    clear_link,
    poll_link,
    read_account,
    start_link,
)

logger = get_logger("api.routes.plex_auth")

router = APIRouter(tags=["plex-auth"])


@router.post("/auth/plex/pin")
def create_pin(
    request: Request,
    handoff: Annotated[str, Form()] = "forward",
    forward_url: Annotated[str, Form()] = "",
) -> dict:
    """Start Plex sign-in: return a PIN, its code, and the URL to approve it."""
    start = start_link(
        handoff=handoff,
        forward_url=forward_url,
        origin=request.headers.get("origin"),
    )
    logger.info("Plex sign-in started (handoff=%s)", start.handoff)
    return start.model_dump()


@router.get("/auth/plex/pin/{pin_id}")
def check_pin(pin_id: int) -> dict:
    """Poll a PIN; once approved, the token is validated and saved locally."""
    result = poll_link(pin_id)
    if result.linked:
        logger.info("Plex sign-in completed (token_saved=%s)", result.token_saved)
    return result.model_dump()


@router.get("/auth/plex/account")
def get_account() -> dict:
    """Report the linked Plex account; the token itself is never returned."""
    account = read_account()
    return {
        "linked": account is not None,
        "account": account.model_dump() if account is not None else None,
    }


@router.post("/auth/plex/unlink")
def unlink() -> dict:
    """Forget the stored Plex token (revoke it in Plex to also drop the device)."""
    return {"unlinked": clear_link()}
