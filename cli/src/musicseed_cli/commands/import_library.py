"""``import`` command: import metadata from the Plex database."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from musicseed.config import get_config
from musicseed.exceptions import NotFoundError
from musicseed.logging_config import get_logger

from musicseed_cli.console import console


def import_library(
    plex_db: Annotated[
        Optional[Path],
        typer.Option("--plex-db", help="Path to Plex SQLite database"),
    ] = None,
    library: Annotated[
        str,
        typer.Option("--library", "-l", help="Plex library name to import"),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Full re-import (default: incremental)"),
    ] = False,
) -> None:
    """Import metadata from the Plex database.

    Reads artists, albums, tracks, and play history from Plex's own SQLite
    database into MusicSeed. Incremental by default — pass --full for a
    complete re-import.
    """
    from musicseed.services import library as library_service

    config = get_config()
    db_path = plex_db or config.plex.db_path_expanded
    target_library = library or config.plex.library

    console.print("\n[bold]Importing from Plex database[/bold]")
    console.print(f"  Database: {db_path}")
    console.print(f"  Library: {target_library}")
    console.print(f"  Mode: {'Full' if full else 'Incremental'}\n")

    try:
        result = library_service.import_library(
            plex_db_path=plex_db,
            library_name=library,
            full_import=full,
        )
        console.print("\n[green]✓ Import completed![/green]")
        console.print(f"  Artists: {result.artists:,}")
        console.print(f"  Albums: {result.albums:,}")
        console.print(f"  Tracks: {result.tracks:,}")
        console.print(f"  Play history: {result.play_history:,}\n")
    except NotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("\nPlease specify the path with --plex-db or update your config file.")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Import failed: {e}")
        console.print(f"[red]✗ Import failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the ``import`` command to the Typer app."""
    app.command("import")(import_library)
