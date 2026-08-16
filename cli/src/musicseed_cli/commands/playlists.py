"""``playlists`` command: list existing Plex audio playlists."""

import typer
from musicseed.exceptions import ConfigurationError
from musicseed.logging_config import get_logger
from rich.table import Table

from musicseed_cli.console import console


def playlists() -> None:
    """List existing Plex audio playlists."""
    from musicseed.services import populate as populate_service

    try:
        results = populate_service.list_plex_playlists()
    except ConfigurationError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Listing Plex playlists failed: {e}")
        console.print(f"[red]✗ Listing Plex playlists failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No audio playlists found in Plex.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Plex Playlists")
    table.add_column("Rating Key", justify="right", style="cyan")
    table.add_column("Name", style="green")
    for playlist_result in results:
        table.add_row(playlist_result.rating_key, playlist_result.title)
    console.print()
    console.print(table)
    console.print(f"\n[green]{len(results)} playlists.[/green]\n")


def register(app: typer.Typer) -> None:
    """Attach the ``playlists`` command to the Typer app."""
    app.command()(playlists)
