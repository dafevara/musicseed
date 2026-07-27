"""CLI command modules.

Each module owns a single command and exposes a ``register(app)`` function
that attaches it to the shared Typer application.
"""

import typer

from musicseed_cli.commands import (
    embed,
    enrich,
    import_library,
    import_plex_sonic,
    init_db,
    optimize_db,
    playlist,
    playlists,
    populate,
    recommend,
    sonic_probe,
    sonic_refresh,
    status,
)

_MODULES = (
    init_db,
    optimize_db,
    status,
    import_library,
    import_plex_sonic,
    sonic_probe,
    sonic_refresh,
    enrich,
    embed,
    recommend,
    playlist,
    playlists,
    populate,
)


def register_all(app: typer.Typer) -> None:
    """Register every command module on the given Typer app."""
    for module in _MODULES:
        module.register(app)
