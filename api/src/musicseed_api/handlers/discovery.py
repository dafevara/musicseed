"""Discovery orchestration — wizard readiness, config overrides, database init.

Handlers take plain Python arguments and return Pydantic models. They never
import FastAPI, Starlette, or any HTTP framework — the same handler is
callable from the CLI, a JSON route, or the web rendering layer.
"""

from __future__ import annotations

from musicseed.config import Config, get_config, save_config
from musicseed.db.session import reset_engine
from musicseed.services.discovery import DiscoveryResult, Reason, discover
from musicseed.services.library import initialize_database
from musicseed.services.plex_discovery import DiscoveredPlexServer, discover_plex_servers

DB_BLOCKERS = frozenset({Reason.NOT_A_FILE, Reason.NOT_WRITABLE, Reason.PARENT_NOT_WRITABLE})

DISCOVERY_KEYS = frozenset({
    "musicseed_db_path", "plex_db_path", "plex_url", "plex_token", "plex_library",
})

_SECRET_FIELDS = frozenset({"plex_token", "spotify_client_secret"})


def wizard_ready(result: DiscoveryResult) -> bool:
    """True when every prerequisite for database creation is met."""
    return (
        result.musicseed_db.reason not in DB_BLOCKERS
        and result.plex_library_db.ok
        and result.plex_blobs_db.ok
        and result.plex_server.ok
    )


def run_discovery(**overrides: str) -> DiscoveryResult:
    """Run local discovery, passing only recognized keys as overrides."""
    filtered = {k: v for k, v in overrides.items() if k in DISCOVERY_KEYS and v}
    return discover(**filtered)


def run_plex_discovery(timeout: float = 3.0) -> list[DiscoveredPlexServer]:
    """Discover Plex servers on the local network (passive GDM + SSDP).

    This is a separate, opt-in probe — it never runs as part of ``discover()``.
    """
    return discover_plex_servers(timeout=timeout)


def extract_overrides(**raw: str) -> tuple[dict[str, str], dict[str, str]]:
    """Split raw form fields into (discovery_overrides, sticky_form_values).

    Blank values are dropped. ``sticky_form_values`` excludes secret fields
    so tokens are never echoed back to the caller.
    """
    stripped = {k: v.strip() for k, v in raw.items() if v.strip()}
    form = {k: v for k, v in stripped.items() if k not in _SECRET_FIELDS}
    return stripped, form


def _apply_config_overrides(
    cfg: Config,
    *,
    musicseed_db_path: str = "",
    spotify_client_id: str = "",
    spotify_client_secret: str = "",
    plex_url: str = "",
    plex_token: str = "",
    plex_library: str = "",
    plex_db_path: str = "",
) -> bool:
    """Apply non-blank overrides to ``cfg`` in place; return True if anything changed."""
    changed = False
    if musicseed_db_path:
        cfg.database.path = musicseed_db_path
        changed = True
    if spotify_client_id:
        cfg.spotify.client_id = spotify_client_id
        changed = True
    if spotify_client_secret:
        cfg.spotify.client_secret = spotify_client_secret
        changed = True
    if plex_url:
        cfg.plex.url = plex_url
        changed = True
    if plex_token:
        cfg.plex.token = plex_token
        changed = True
    if plex_library:
        cfg.plex.library = plex_library
        changed = True
    if plex_db_path:
        cfg.plex.db_path = plex_db_path
        changed = True
    return changed


def save_config_overrides(
    musicseed_db_path: str = "",
    spotify_client_id: str = "",
    spotify_client_secret: str = "",
    plex_url: str = "",
    plex_token: str = "",
    plex_library: str = "",
    plex_db_path: str = "",
) -> bool:
    """Persist setup overrides to config without any side effects.

    Saves credentials and paths only — never creates the database, starts an
    import, or runs enrichment. Returns True when anything changed. Blank
    fields leave the existing config untouched.
    """
    cfg = get_config()
    changed = _apply_config_overrides(
        cfg,
        musicseed_db_path=musicseed_db_path,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
        plex_db_path=plex_db_path,
    )
    if changed:
        save_config(cfg)
        reset_engine()
    return changed


def apply_config_and_init_db(
    musicseed_db_path: str = "",
    spotify_client_id: str = "",
    spotify_client_secret: str = "",
    plex_url: str = "",
    plex_token: str = "",
    plex_library: str = "",
    plex_db_path: str = "",
) -> None:
    """Persist validated setup overrides to config and create the database.

    Carries the Plex settings that passed discovery into config so import
    uses the same values the user confirmed. Blank fields leave the existing
    config untouched. Raises whatever ``initialize_database`` or the config
    layer raises; callers are expected to catch and map to their own error
    convention.
    """
    save_config_overrides(
        musicseed_db_path=musicseed_db_path,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        plex_url=plex_url,
        plex_token=plex_token,
        plex_library=plex_library,
        plex_db_path=plex_db_path,
    )
    initialize_database()
