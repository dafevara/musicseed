"""``import-plex-sonic`` command: import Plex sonic vectors into the local store."""

import typer
from musicseed.exceptions import NotFoundError
from musicseed.logging_config import get_logger

from musicseed_cli.console import console


def import_plex_sonic() -> None:
    """Import Plex sonic-analysis vectors into the local database.

    Reads the Plex blobs database once and persists every vector into
    MusicSeed's local store so recommendations no longer need the blobs file
    at query time. Idempotent — re-run after Plex analyzes more tracks to
    refresh the store.
    """
    from musicseed.services import sonic_vectors as sonic_vectors_service

    console.print("\n[bold]Importing Plex sonic vectors[/bold]\n")

    try:
        with console.status("[bold green]Reading Plex blobs database..."):
            result = sonic_vectors_service.import_plex_sonic()
        console.print("[green]✓ Sonic vectors imported.[/green]")
        console.print(f"  Found in Plex: {result.total:,}")
        console.print(f"  Newly imported: {result.imported:,}")
        console.print(f"  Updated: {result.updated:,}\n")
    except NotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print(
            "\nMusicSeed reads the blobs database "
            "(com.plexapp.plugins.library.blobs.db) from the Plex database "
            "folder. Point plex.db_path at your Plex library database, or copy "
            "both files locally first."
        )
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Sonic vector import failed: {e}")
        console.print(f"[red]✗ Sonic vector import failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the ``import-plex-sonic`` command to the Typer app."""
    app.command("import-plex-sonic")(import_plex_sonic)
