"""CLI command modules.

Each module owns a single command and exposes a ``register(app)`` function
that attaches it to the shared Typer application.
"""

import typer

from musicseed_cli.commands import (
    enrich,
    import_library,
    init_db,
    optimize_db,
    playlist,
    playlists,
    populate,
    recommend,
    sonic_probe,
    sonic_refresh,
    status,
    web,
)

_MODULES = (
    web,
    init_db,
    optimize_db,
    status,
    import_library,
    sonic_probe,
    sonic_refresh,
    enrich,
    recommend,
    playlist,
    playlists,
    populate,
)


def register_all(app: typer.Typer) -> None:
    """Register every command module on the given Typer app."""
    for module in _MODULES:
        module.register(app)
