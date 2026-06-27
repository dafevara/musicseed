"""Configuration loading and management."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values."""
    if isinstance(value, str):
        return os.path.expandvars(os.path.expanduser(value))
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "musicseed"
    user: str = "musicseed"
    password: str = ""

    @property
    def url(self) -> str:
        # Use postgresql+psycopg for psycopg3 driver
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass
class PlexConfig:
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


@dataclass
class SpotifyConfig:
    client_id: str = ""
    client_secret: str = ""


@dataclass
class EmbeddingConfig:
    model: str = "essentia"
    batch_size: int = 10
    workers: int = 4


@dataclass
class EnrichmentConfig:
    concurrency: int = 5
    batch_size: int = 50


@dataclass
class LoggingConfig:
    level: str = "INFO"
    console: bool = False
    console_level: str = "WARNING"


@dataclass
class RecommendationWeights:
    sonic: float = 0.30
    popularity: float = 0.15  # Popularity proximity, not absolute popularity boost
    mood: float = 0.15
    style: float = 0.10
    genre: float = 0.15
    era: float = 0.05
    novelty: float = 0.10


@dataclass
class RecommendationConfig:
    default_weights: RecommendationWeights = field(default_factory=RecommendationWeights)
    default_limit: int = 50
    max_tracks_per_artist: int = 3


@dataclass
class Config:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    plex: PlexConfig = field(default_factory=PlexConfig)
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    recommendation: RecommendationConfig = field(default_factory=RecommendationConfig)


def _dict_to_dataclass(cls, data: dict) -> Any:
    """Convert a dictionary to a dataclass, handling nested dataclasses."""
    if data is None:
        return cls()

    field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}
    kwargs = {}

    for key, value in data.items():
        if key in field_types:
            field_type = field_types[key]
            # Handle nested dataclasses
            if hasattr(field_type, "__dataclass_fields__") and isinstance(value, dict):
                kwargs[key] = _dict_to_dataclass(field_type, value)
            else:
                kwargs[key] = value

    return cls(**kwargs)


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses default locations.

    Returns:
        Loaded Config object with environment variables expanded.
    """
    if config_path is None:
        # Default config locations
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
        # Return default config
        return Config()

    with open(config_path) as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        return Config()

    # Expand environment variables
    raw_config = _expand_env_vars(raw_config)

    # Build config object
    config = Config(
        database=_dict_to_dataclass(DatabaseConfig, raw_config.get("database", {})),
        plex=_dict_to_dataclass(PlexConfig, raw_config.get("plex", {})),
        spotify=_dict_to_dataclass(SpotifyConfig, raw_config.get("spotify", {})),
        embedding=_dict_to_dataclass(EmbeddingConfig, raw_config.get("embedding", {})),
        enrichment=_dict_to_dataclass(EnrichmentConfig, raw_config.get("enrichment", {})),
        logging=_dict_to_dataclass(LoggingConfig, raw_config.get("logging", {})),
        recommendation=_dict_to_dataclass(
            RecommendationConfig, raw_config.get("recommendation", {})
        ),
    )

    return config


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
