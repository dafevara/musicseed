"""Configuration loading and management."""

import ipaddress
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field

_PLEX_LIBRARY_DB = (
    Path("Plug-in Support") / "Databases" / "com.plexapp.plugins.library.db"
)


def default_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "musicseed"


def default_log_dir() -> Path:
    return default_data_dir() / "logs"


def plex_data_dir_candidates() -> list[Path]:
    home = Path.home()
    return [
        home / "Library" / "Application Support" / "Plex Media Server",
        Path("/var/lib/plexmediaserver/Library/Application Support/Plex Media Server"),
        Path(
            "/var/snap/plexmediaserver/common/Library/Application Support/"
            "Plex Media Server"
        ),
        home
        / ".local"
        / "share"
        / "plexmediaserver"
        / "Library"
        / "Application Support"
        / "Plex Media Server",
    ]


def default_plex_data_dir() -> Path:
    for path in plex_data_dir_candidates():
        if path.is_dir():
            return path
    if sys.platform.startswith("linux"):
        return Path(
            "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server"
        )
    return Path.home() / "Library" / "Application Support" / "Plex Media Server"


def plex_library_db_candidates() -> list[Path]:
    return [directory / _PLEX_LIBRARY_DB for directory in plex_data_dir_candidates()]


def default_plex_db_path() -> str:
    return str(default_plex_data_dir() / _PLEX_LIBRARY_DB)


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values."""
    if isinstance(value, str):
        return os.path.expandvars(os.path.expanduser(value))
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


_LOCAL_HOST_SUFFIXES = (
    ".local", ".lan", ".home", ".home.arpa", ".internal", ".localhost",
    ".localdomain", ".ts.net",
)


def _ip(host: str):
    """Parse ``host`` as an IP address, or return None for a hostname."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _is_local_hostname(host: str) -> bool:
    """True for a home-network or VPN hostname (mDNS / single-label / known suffixes)."""
    host = host.lower()
    if host == "localhost":
        return True
    if "." not in host:
        return True
    return host.endswith(_LOCAL_HOST_SUFFIXES)


def url_is_remote_cleartext(url: str) -> bool:
    """True when ``url`` is plain ``http://`` to a globally routable host.

    Local, home-LAN, and VPN addresses — loopback, RFC1918 private, link-local,
    CGNAT/Tailscale (100.64.0.0/10), IPv6 ULA, and ``.local``/``.ts.net``
    hostnames — keep working over ``http://``. Only a *publicly routable* host
    is treated as remote, where cleartext would expose the token to the internet.
    """
    parsed = urlparse(url)
    if (parsed.scheme or "").lower() != "http":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if _is_local_hostname(host):
        return False
    ip = _ip(host)
    if ip is None:
        return True  # a non-local hostname is remote by default
    # ``is_global`` is False for private/loopback/link-local/CGNAT/ULA and True
    # only for globally routable addresses — exactly the remote case.
    return ip.is_global


class DatabaseConfig(BaseModel):
    path: str = "~/.local/share/musicseed/musicseed.db"

    @property
    def path_expanded(self) -> Path:
        return Path(os.path.expanduser(self.path))

    @property
    def url(self) -> str:
        """SQLAlchemy connection URL only — never pass this to ``sqlite3.connect``.

        Filesystem callers must use ``path_expanded`` (``url`` is a ``sqlite://``
        URL, not a path).
        """
        return f"sqlite:///{self.path_expanded}"


class PlexConfig(BaseModel):
    url: str = "http://localhost:32400"
    token: str = ""
    library: str = "Music"
    # Stable identifier for this MusicSeed install, sent to plex.tv as
    # ``X-Plex-Client-Identifier``. Generated once by the Plex sign-in flow and
    # reused forever: Plex keys the "Authorized Devices" entry and in-flight
    # PINs to it, so rotating it would orphan both.
    client_identifier: str = ""
    db_path: str = Field(default_factory=default_plex_db_path)
    # Optional scp-style SSH target for a remote Plex server, e.g.
    # ``"admin@nas.local:/volume1/Plex/.../Databases"``. When set, MusicSeed
    # creates standalone SQLite backups on the host and streams them over
    # verified SSH on each import. Empty means "use the local db_path".
    db_ssh_target: str = ""
    # Optional SSH password. Leave empty to use the user's ``~/.ssh`` keys
    # and agent instead.
    db_ssh_password: str = ""
    db_ssh_port: int = 22
    # Opt-in for a plain http:// connection to a remote (non-local) Plex host.
    # Defaults False so a remote cleartext connection is a deliberate choice;
    # prefer https:// or a VPN/tunnel instead.
    allow_cleartext_remote: bool = False

    @property
    def db_path_expanded(self) -> Path:
        return Path(os.path.expanduser(self.db_path))

    @property
    def blobs_db_path_expanded(self) -> Path:
        """Path to the Plex blobs database, which holds sonic analysis vectors."""
        db_path = self.db_path_expanded
        return db_path.with_name(f"{db_path.stem}.blobs{db_path.suffix}")


class SpotifyConfig(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class ListenBrainzConfig(BaseModel):
    # User token from https://listenbrainz.org/settings/ — required for
    # ListenBrainz enrichment (authenticated requests get higher rate limits).
    token: str = ""


class EnrichmentConfig(BaseModel):
    concurrency: int = 5
    batch_size: int = 50


class LoggingConfig(BaseModel):
    level: str = "INFO"
    console: bool = False
    console_level: str = "WARNING"


class RecommendationWeights(BaseModel):
    sonic: float = 0.30
    popularity: float = 0.15
    style: float = 0.10
    genre: float = 0.15
    era: float = 0.05
    novelty: float = 0.10


class RecommendationConfig(BaseModel):
    default_weights: RecommendationWeights = Field(default_factory=RecommendationWeights)
    default_limit: int = 50
    max_tracks_per_artist: int = 3


class SecurityConfig(BaseModel):
    #: Extra hostnames (beyond loopback and private addresses) allowed to reach
    #: the API, e.g. a home-network DNS name. Compared lowercased, no port.
    allowed_hosts: list[str] = Field(default_factory=list)
    #: Auto-generated CSRF secret. Written owner-only (0600) on first use so the
    #: browser CSRF token survives restarts. Leave empty; never set by hand.
    csrf_secret: str = ""


class LimitsConfig(BaseModel):
    #: Maximum request body (form data) the JSON API will accept, in bytes.
    max_request_body_bytes: int = 1_048_576
    #: Maximum seed tracks accepted per recommendation/preview request.
    max_seeds: int = 50
    #: Maximum approved tracks accepted per playlist create/populate.
    max_selection_tracks: int = 500
    #: Maximum matches returned by a single typeahead search.
    max_search_results: int = 50
    #: Maximum recommendations returned by a single recommendation/preview call.
    max_recommendations: int = 200
    #: Upper bound on the total size of a remote Plex database snapshot, in bytes.
    max_snapshot_bytes: int = 20 * 1024**3


class Config(BaseModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    plex: PlexConfig = Field(default_factory=PlexConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    listenbrainz: ListenBrainzConfig = Field(default_factory=ListenBrainzConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    recommendation: RecommendationConfig = Field(default_factory=RecommendationConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses default locations.

    Returns:
        Loaded Config object with environment variables expanded.
    """
    global _config_path
    if config_path is None:
        candidates = [
            Path.home() / ".config" / "musicseed" / "config.yaml",
            Path.home() / ".musicseed.yaml",
            Path("config.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None or not config_path.exists():
        _config_path = None
        return Config()

    _config_path = Path(config_path)
    with open(config_path) as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        return Config()

    raw_config = _expand_env_vars(raw_config)
    return Config.model_validate(raw_config)


# Global config instance (lazy loaded)
_config: Config | None = None
_config_path: Path | None = None


def default_config_path() -> Path:
    """Canonical config location used when no existing file was resolved."""
    return Path.home() / ".config" / "musicseed" / "config.yaml"


def get_config() -> Config:
    """Get the operation-bound config, falling back to the process default."""
    from musicseed.context import get_bound_context

    bound = get_bound_context()
    if bound is not None:
        return bound.config
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_config_path() -> Path | None:
    """Return the resolved config file path, or None if no file was found.

    Used by discovery to derive the "no config file yet" first-run signal.
    """
    return _config_path


def set_config(config: Config) -> None:
    """Set the global config instance and drop the derived runtime context.

    The default ``MusicSeedContext`` caches an engine and sonic vectors derived
    from config, so replacing the config must invalidate it; the next access
    rebuilds from this config.
    """
    global _config
    _config = config
    from musicseed.context import reset_context

    reset_context()


def save_config(config: Config, path: Path | None = None) -> Path:
    """Persist ``config`` to the YAML file it was loaded from (or ``path``).

    Writes back to the path ``load_config`` resolved and records it so later
    saves target the same file. Falls back to the canonical default location
    when no file has been resolved yet.

    The file holds credentials (Plex token, provider secrets), so it is created
    and kept owner-only (``0600``).

    Returns:
        The path written to.
    """
    global _config_path
    target = Path(path) if path is not None else (_config_path or default_config_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write to an owner-only temp file in the same directory, then atomically
    # replace the target. ``mkstemp`` creates the temp with mode 0600, so secrets
    # are never written to a world-readable file; ``os.replace`` means an
    # interruption cannot leave a half-written configuration behind.
    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(config.model_dump(), f, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    try:
        # Belt-and-suspenders on filesystems that ignore the temp mode.
        target.chmod(0o600)
    except OSError:  # pragma: no cover - non-POSIX filesystems
        pass
    _config_path = target
    return target


def reload_config() -> Config:
    """Re-read the config file from disk and install it as the process config.

    Long-running surfaces (the MCP server in particular) cache config at
    startup, so credentials added by another surface — e.g. a Plex sign-in
    completed in the web UI — would otherwise stay invisible until restart.
    """
    path = _config_path
    config = load_config(path) if path is not None else load_config()
    set_config(config)
    return config
