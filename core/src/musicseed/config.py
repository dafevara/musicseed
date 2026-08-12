"""Configuration loading and management."""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values."""
    if isinstance(value, str):
        return os.path.expandvars(os.path.expanduser(value))
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


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
    db_path: str = (
        "~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/"
        "com.plexapp.plugins.library.db"
    )

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


class Config(BaseModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    plex: PlexConfig = Field(default_factory=PlexConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    recommendation: RecommendationConfig = Field(default_factory=RecommendationConfig)


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
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(config: Config) -> None:
    """Set the global config instance."""
    global _config
    _config = config


def save_config(config: Config, path: Path | None = None) -> Path:
    """Persist ``config`` to the YAML file it was loaded from (or ``path``).

    Writes back to the path ``load_config`` resolved and records it so later
    saves target the same file. Falls back to the canonical default location
    when no file has been resolved yet.

    Returns:
        The path written to.
    """
    global _config_path
    target = Path(path) if path is not None else (_config_path or default_config_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w") as f:
        yaml.safe_dump(config.model_dump(), f, sort_keys=False)
    _config_path = target
    return target
