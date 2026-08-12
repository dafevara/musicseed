"""Local environment discovery: Plex server, databases, and config state.

Surface-agnostic and strictly read-only: probes the filesystem and the Plex
HTTP API (GET requests only) but never starts imports, sonic analysis,
enrichment, or any Plex mutation. Expected failures are returned as
structured data (``reason`` codes) so surfaces can render actionable fixes
instead of parsing exceptions. Plex tokens are never included in results.
"""

import os
import sqlite3
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

from pydantic import BaseModel

from musicseed.clients.plex import PlexClient
from musicseed.config import (
    Config,
    DatabaseConfig,
    PlexConfig,
    get_config,
    get_config_path,
)

_SQLITE_HEADER = b"SQLite format 3\x00"


def _plex_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Plex Media Server"


def read_plex_token(
    preferences_path: str | None = None,
    local_admin_token_path: str | None = None,
) -> str | None:
    """Read a usable Plex token from the local server's data directory.

    Prefers the account token (``PlexOnlineToken`` in ``Preferences.xml``),
    then falls back to ``.LocalAdminToken`` (which only works from localhost).
    Returns ``None`` when neither is readable. Read-only — the token value is
    never logged or returned in discovery results.
    """
    prefs = Path(preferences_path) if preferences_path else _plex_data_dir() / "Preferences.xml"
    try:
        root = ElementTree.parse(prefs).getroot()
    except (OSError, ElementTree.ParseError):
        token = None
    else:
        token = (root.get("PlexOnlineToken") or "").strip() or None
    if token:
        return token

    admin = (
        Path(local_admin_token_path)
        if local_admin_token_path
        else _plex_data_dir() / ".LocalAdminToken"
    )
    try:
        return admin.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


class Reason(StrEnum):
    """Machine-readable discovery outcome codes."""

    OK = "ok"
    SKIPPED = "skipped"
    NOT_FOUND = "not_found"
    NOT_A_FILE = "not_a_file"
    NOT_READABLE = "not_readable"
    NOT_WRITABLE = "not_writable"
    INVALID_SQLITE = "invalid_sqlite"
    PARENT_MISSING = "parent_missing"
    PARENT_NOT_WRITABLE = "parent_not_writable"
    MISSING_TOKEN = "missing_token"
    UNREACHABLE = "unreachable"
    UNAUTHORIZED = "unauthorized"
    LIBRARY_NOT_FOUND = "library_not_found"
    ERROR = "error"


class PathCandidate(BaseModel):
    """One probed filesystem candidate for a required local file."""

    model_config = {"frozen": True}

    path: str
    source: str  # "override", "config", or "default"
    exists: bool
    usable: bool
    reason: Reason
    detail: str | None = None


class FileDiscovery(BaseModel):
    """Discovery result for a required local file (e.g. a Plex database)."""

    model_config = {"frozen": True}

    candidates: list[PathCandidate]
    selected: PathCandidate | None
    ok: bool


class DatabasePathDiscovery(BaseModel):
    """Discovery result for MusicSeed's own SQLite database location."""

    model_config = {"frozen": True}

    path: str
    source: str
    exists: bool
    writable: bool  # existing file can be written
    creatable: bool  # file does not exist yet but the parent dir is writable
    reason: Reason
    detail: str | None = None
    ok: bool


class PlexServerDiscovery(BaseModel):
    """Discovery result for the Plex HTTP API."""

    model_config = {"frozen": True}

    url: str
    source: str
    token_configured: bool
    token_source: str = "none"  # "override" | "config" | "local" | "none"
    server_version: str | None
    library: str
    library_found: bool
    reason: Reason
    detail: str | None = None
    ok: bool


class SpotifyCredentialsCheck(BaseModel):
    """Presence of Spotify enrichment credentials (values never exposed)."""

    model_config = {"frozen": True}

    configured: bool
    client_id_set: bool
    client_secret_set: bool


class EnrichmentDiscovery(BaseModel):
    """Enrichment-provider readiness. ListenBrainz needs no credentials."""

    model_config = {"frozen": True}

    spotify: SpotifyCredentialsCheck
    listenbrainz_requires_key: bool = False


class FirstRunStatus(BaseModel):
    """Derived first-run state and the reasons it is considered a first run."""

    model_config = {"frozen": True}

    no_config: bool
    db_missing: bool
    library_empty: bool
    is_first_run: bool
    reasons: list[str]


class DiscoveryResult(BaseModel):
    """Complete, read-only picture of the local MusicSeed environment."""

    model_config = {"frozen": True}

    musicseed_db: DatabasePathDiscovery
    plex_library_db: FileDiscovery
    plex_blobs_db: FileDiscovery
    plex_server: PlexServerDiscovery
    ready: bool  # every check ok; surfaces can gate "start import" on this
    enrichers: EnrichmentDiscovery
    first_run: FirstRunStatus
    missing_inputs: list[str]


def _probe_file(path: Path, source: str) -> PathCandidate:
    """Read-only validation of a file that must exist (existence, access, SQLite header)."""
    if not path.exists():
        return PathCandidate(
            path=str(path), source=source, exists=False, usable=False,
            reason=Reason.NOT_FOUND, detail="File does not exist.",
        )
    if not path.is_file():
        return PathCandidate(
            path=str(path), source=source, exists=True, usable=False,
            reason=Reason.NOT_A_FILE, detail="Path exists but is not a file.",
        )
    if not os.access(path, os.R_OK):
        return PathCandidate(
            path=str(path), source=source, exists=True, usable=False,
            reason=Reason.NOT_READABLE,
            detail="File is not readable by the current user.",
        )
    try:
        with open(path, "rb") as f:
            header = f.read(len(_SQLITE_HEADER))
    except OSError as e:
        return PathCandidate(
            path=str(path), source=source, exists=True, usable=False,
            reason=Reason.NOT_READABLE, detail=f"Could not open file: {e}",
        )
    if header != _SQLITE_HEADER:
        return PathCandidate(
            path=str(path), source=source, exists=True, usable=False,
            reason=Reason.INVALID_SQLITE,
            detail="File exists but is not a SQLite database.",
        )
    return PathCandidate(
        path=str(path), source=source, exists=True, usable=True, reason=Reason.OK
    )


def _discover_file(candidates: list[tuple[Path, str]]) -> FileDiscovery:
    probed = [_probe_file(path, source) for path, source in candidates]
    selected = next((c for c in probed if c.usable), None)
    return FileDiscovery(candidates=probed, selected=selected, ok=selected is not None)


def _discover_musicseed_db(path: Path, source: str) -> DatabasePathDiscovery:
    """Check whether MusicSeed's own database exists and is writable/creatable."""
    if path.exists():
        if not path.is_file():
            return DatabasePathDiscovery(
                path=str(path), source=source, exists=True, writable=False, creatable=False,
                reason=Reason.NOT_A_FILE, detail="Path exists but is not a file.", ok=False,
            )
        writable = os.access(path, os.W_OK)
        return DatabasePathDiscovery(
            path=str(path), source=source, exists=True, writable=writable, creatable=False,
            reason=Reason.OK if writable else Reason.NOT_WRITABLE,
            detail=None if writable else "Database file is not writable by the current user.",
            ok=writable,
        )

    parent = path.parent
    if not parent.exists():
        return DatabasePathDiscovery(
            path=str(path), source=source, exists=False, writable=False, creatable=False,
            reason=Reason.PARENT_MISSING,
            detail=f"Directory {parent} does not exist yet.",
            ok=False,
        )
    if not os.access(parent, os.W_OK):
        return DatabasePathDiscovery(
            path=str(path), source=source, exists=False, writable=False, creatable=False,
            reason=Reason.PARENT_NOT_WRITABLE,
            detail=f"Directory {parent} is not writable by the current user.",
            ok=False,
        )
    return DatabasePathDiscovery(
        path=str(path), source=source, exists=False, writable=False, creatable=True,
        reason=Reason.OK,
        detail="Database does not exist yet but can be created here.",
        ok=True,
    )


def _source(override: str | None, configured: str, default: str) -> str:
    if override is not None:
        return "override"
    return "config" if configured != default else "default"


def _dedup_candidates(entries: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    seen: set[str] = set()
    unique: list[tuple[Path, str]] = []
    for path, source in entries:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append((path, source))
    return unique


def _discover_server(
    url: str, source: str, token: str, library: str, timeout: float, token_source: str
) -> PlexServerDiscovery:
    token_configured = bool(token)
    client = PlexClient(url, token, timeout=timeout)
    base = {
        "url": url,
        "source": source,
        "token_configured": token_configured,
        "token_source": token_source,
        "library": library,
    }

    try:
        check = client.check_connection()
    except Exception as e:  # defensive: discovery must not raise
        return PlexServerDiscovery(
            **base, server_version=None, library_found=False,
            reason=Reason.ERROR, detail=f"Unexpected error: {e}", ok=False,
        )

    if not check.reachable:
        return PlexServerDiscovery(
            **base, server_version=None, library_found=False,
            reason=Reason.UNREACHABLE, detail=check.error, ok=False,
        )
    if not check.authorized:
        reason = Reason.UNAUTHORIZED if token_configured else Reason.MISSING_TOKEN
        detail = (
            "Plex rejected the configured token."
            if token_configured
            else "No Plex token configured; the server requires one."
        )
        return PlexServerDiscovery(
            **base, server_version=check.server_version, library_found=False,
            reason=reason, detail=detail, ok=False,
        )
    if check.status_code != 200:
        return PlexServerDiscovery(
            **base, server_version=check.server_version, library_found=False,
            reason=Reason.ERROR, detail=check.error, ok=False,
        )

    try:
        sections = client.list_library_sections()
    except Exception as e:  # reachable + authorized but sections failed
        return PlexServerDiscovery(
            **base, server_version=check.server_version, library_found=False,
            reason=Reason.ERROR, detail=f"Could not list library sections: {e}", ok=False,
        )
    library_found = any(s.title == library and s.type == "artist" for s in sections)
    return PlexServerDiscovery(
        **base,
        server_version=check.server_version,
        library_found=library_found,
        reason=Reason.OK if library_found else Reason.LIBRARY_NOT_FOUND,
        detail=(
            None
            if library_found
            else f"No music library named '{library}' found on this server."
        ),
        ok=library_found,
    )


def discover(
    *,
    musicseed_db_path: str | None = None,
    plex_db_path: str | None = None,
    plex_url: str | None = None,
    plex_token: str | None = None,
    plex_library: str | None = None,
    check_server: bool = True,
    timeout: float = 5.0,
    config: Config | None = None,
) -> DiscoveryResult:
    """Probe the local MusicSeed/Plex environment. Read-only; never raises on
    expected failures — they are reported via ``reason`` codes instead.

    Overrides apply to this call only and never mutate global configuration.
    """
    cfg = config if config is not None else get_config()
    default_plex = PlexConfig()

    # MusicSeed's own database (single effective path)
    db_value = musicseed_db_path or cfg.database.path
    db_source = _source(musicseed_db_path, cfg.database.path, DatabaseConfig().path)
    musicseed_db = _discover_musicseed_db(
        Path(os.path.expanduser(db_value)), db_source
    )

    # Plex library database (candidates: override/config value, then the default)
    plex_value = plex_db_path or cfg.plex.db_path
    plex_source = _source(plex_db_path, cfg.plex.db_path, default_plex.db_path)
    library_candidates = _dedup_candidates([
        (Path(os.path.expanduser(plex_value)), plex_source),
        (default_plex.db_path_expanded, "default"),
    ])
    plex_library_db = _discover_file(library_candidates)

    # Plex blobs database (derived from each library-db candidate, as in
    # PlexConfig.blobs_db_path_expanded)
    blobs_candidates = _dedup_candidates([
        (PlexConfig(db_path=str(path)).blobs_db_path_expanded, source)
        for path, source in library_candidates
    ])
    plex_blobs_db = _discover_file(blobs_candidates)

    # Plex HTTP API
    url = plex_url or cfg.plex.url
    url_source = _source(plex_url, cfg.plex.url, default_plex.url)
    library = plex_library or cfg.plex.library
    if plex_token is not None:
        token, token_source = plex_token, "override"
    elif cfg.plex.token:
        token, token_source = cfg.plex.token, "config"
    else:
        local_token = read_plex_token()
        token, token_source = (local_token, "local") if local_token else ("", "none")
    if check_server:
        plex_server = _discover_server(
            url, url_source, token, library, timeout, token_source
        )
    else:
        plex_server = PlexServerDiscovery(
            url=url,
            source=url_source,
            token_configured=bool(token),
            token_source=token_source,
            server_version=None,
            library=library,
            library_found=False,
            reason=Reason.SKIPPED,
            detail="Server check not requested.",
            ok=False,
        )

    ready = all([
        musicseed_db.ok,
        plex_library_db.ok,
        plex_blobs_db.ok,
        plex_server.ok,
    ])

    spotify = SpotifyCredentialsCheck(
        configured=bool(cfg.spotify.client_id and cfg.spotify.client_secret),
        client_id_set=bool(cfg.spotify.client_id),
        client_secret_set=bool(cfg.spotify.client_secret),
    )
    enrichers = EnrichmentDiscovery(spotify=spotify)

    missing: list[str] = []
    if not musicseed_db.ok:
        missing.append("db_location")
    if not plex_library_db.ok or not plex_blobs_db.ok:
        missing.append("plex_db_path")
    if not plex_server.ok:
        if plex_server.reason in (Reason.MISSING_TOKEN, Reason.UNAUTHORIZED):
            missing.append("plex_token")
        elif plex_server.reason is Reason.UNREACHABLE:
            missing.append("plex_unreachable")
        elif plex_server.reason is Reason.LIBRARY_NOT_FOUND:
            missing.append("plex_library")
        else:
            missing.append("plex_server")
    if not spotify.configured:
        missing.append("spotify_credentials")

    no_config = get_config_path() is None
    db_missing = not musicseed_db.exists
    track_count = _count_tracks(Path(musicseed_db.path)) if not db_missing else None
    library_empty = track_count == 0
    first_run_reasons = [
        reason
        for reason, flag in (
            ("no_config", no_config),
            ("db_missing", db_missing),
            ("library_empty", library_empty),
        )
        if flag
    ]
    first_run = FirstRunStatus(
        no_config=no_config,
        db_missing=db_missing,
        library_empty=library_empty,
        is_first_run=bool(first_run_reasons),
        reasons=first_run_reasons,
    )

    return DiscoveryResult(
        musicseed_db=musicseed_db,
        plex_library_db=plex_library_db,
        plex_blobs_db=plex_blobs_db,
        plex_server=plex_server,
        ready=ready,
        enrichers=enrichers,
        first_run=first_run,
        missing_inputs=missing,
    )


def _count_tracks(db_path: Path) -> int | None:
    """Return the number of imported tracks, or None when undeterminable.

    Opens the discovered database read-only (``mode=ro``) so discovery never
    writes, including sidecar WAL files. Any error — missing file, missing
    schema, locked database — yields None rather than raising.
    """
    if not db_path.exists() or not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        cur = conn.execute("SELECT COUNT(*) FROM tracks")
        return int(cur.fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()
