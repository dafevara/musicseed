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
    host: str = "localhost"
    port: int = 5432
    name: str = "musicseed"
    user: str = "musicseed"
    password: str = ""

    @property
    def url(self) -> str:
        return (
            f"postgresql+psycopg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


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


class SpotifyConfig(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class EmbeddingConfig(BaseModel):
    model: str = "essentia"
    batch_size: int = 10
    workers: int = 4
    model_path: str = ""
    auto_download_model: bool = True


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
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
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
        return Config()

    with open(config_path) as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        return Config()

    raw_config = _expand_env_vars(raw_config)
    return Config.model_validate(raw_config)


# Global config instance (lazy loaded)
_config: Config | None = None


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
