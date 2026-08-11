"""Plex Media Server HTTP API client.

Built against the Plex Media Server OpenAPI spec (v0.2.0) from
https://plexapi.dev — the spec is used as a reference for endpoint
contracts and response shapes, not for code generation.

Package layout
    client.py   — PlexClient transport, auth, error handling
    models.py   — Pydantic response/domain models (spec-aligned)
"""

from musicseed.clients.plex.client import PlexAPIError, PlexClient
from musicseed.clients.plex.models import (
    ActivityInfo,
    ConnectionCheck,
    HubEntry,
    HubResult,
    LibrarySectionResult,
    Media,
    MediaItem,
    Part,
    Playlist,
    Tag,
)

__all__ = [
    "ActivityInfo",
    "ConnectionCheck",
    "HubEntry",
    "HubResult",
    "LibrarySectionResult",
    "Media",
    "MediaItem",
    "Part",
    "Playlist",
    "PlexAPIError",
    "PlexClient",
    "Tag",
]
