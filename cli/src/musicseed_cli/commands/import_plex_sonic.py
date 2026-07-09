"""``import-plex-sonic`` command: import Plex sonic analysis vectors."""

from pathlib import Path
from typing import Annotated, Optional

import typer

from musicseed.config import get_config
from musicseed.exceptions import NotFoundError
from musicseed.logging_config import get_logger

from musicseed_cli.console import console


def import_plex_sonic(
    plex_db: Annotated[
        Optional[Path],
        typer.Option("--plex-db", help="Path to Plex SQLite database"),
    ] = None,
    blobs_db: Annotated[
        Optional[Path],
        typer.Option("--blobs-db", help="Path to Plex blobs SQLite database"),
    ] = None,
    library: Annotated[
        str,
        typer.Option("--library", "-l", help="Plex library name to import"),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace existing MusicSeed embeddings"),
    ] = False,
) -> None:
    """Import Plex sonic analysis vectors."""
    from musicseed.services import library as library_service

    config = get_config()
    db_path = plex_db or config.plex.db_path_expanded
    blobs_path = blobs_db or db_path.with_name(f"{db_path.stem}.blobs{db_path.suffix}")
    target_library = library or config.plex.library

    console.print("\n[bold]Importing Plex sonic analysis[/bold]")
    console.print(f"  Database: {db_path}")
    console.print(f"  Blobs: {blobs_path}")
    console.print(f"  Library: {target_library}")
    console.print(f"  Mode: {'Overwrite' if overwrite else 'Missing only'}\n")

    try:
        result = library_service.import_plex_sonic(
            plex_db_path=plex_db,
            blobs_db_path=blobs_db,
            library_name=library,
            overwrite=overwrite,
        )
        console.print("\n[green]✓ Plex sonic import completed![/green]")
        console.print(f"  Available vectors: {result.available:,}")
        console.print(f"  Imported: {result.imported:,}")
        console.print(f"  Skipped: {result.skipped:,}")
        console.print(f"  Invalid Plex blobs: {result.invalid:,}")
        console.print(f"  Missing MusicSeed tracks: {result.missing:,}\n")
    except NotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Plex sonic import failed: {e}")
        console.print(f"[red]✗ Plex sonic import failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    app.command("import-plex-sonic")(import_plex_sonic)
