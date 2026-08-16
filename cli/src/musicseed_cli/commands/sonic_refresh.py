"""``sonic-refresh`` command: refresh Plex sonic analysis for recent additions."""

from datetime import datetime, timedelta
from typing import Annotated, Optional

import typer
from musicseed.config import get_config
from musicseed.exceptions import ConfigurationError, NotFoundError
from musicseed.logging_config import get_logger
from rich.table import Table

from musicseed_cli.console import console


def _album_table(albums, limit: int = 15) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("Album Key", style="dim")
    table.add_column("Artist")
    table.add_column("Album")
    table.add_column("Pending", justify="right")
    table.add_column("Added")
    for album in albums[:limit]:
        added = (
            album.most_recent_added_at.strftime("%Y-%m-%d")
            if album.most_recent_added_at
            else "?"
        )
        table.add_row(
            album.rating_key,
            album.artist or "?",
            album.title or "?",
            f"{album.unanalyzed_count}/{album.track_count}",
            added,
        )
    console.print(table)
    if len(albums) > limit:
        console.print(f"[dim]  … and {len(albums) - limit} more[/dim]")


def sonic_refresh(
    library: Annotated[
        Optional[str],
        typer.Option("--library", "-l", help="Plex library name (default: config)"),
    ] = None,
    days: Annotated[
        int,
        typer.Option(
            "--days",
            help="Refresh sonic analysis for music added in the last N days",
        ),
    ] = 7,
    wait: Annotated[
        int,
        typer.Option("--wait", help="Max seconds to watch the refresh"),
    ] = 900,
) -> None:
    """Refresh Plex sonic analysis for recently added music.

    Triggers Plex's MusicAnalysis task and watches until the tracks added in
    the last --days days are analyzed. Run ``import-plex-sonic`` afterwards to
    pull the new vectors into MusicSeed.
    """
    from musicseed.services import plex_analysis

    config = get_config()
    target_library = library or config.plex.library

    console.print("\n[bold]Plex sonic analysis refresh[/bold]")
    console.print(f"  Server: {config.plex.url}")
    console.print(f"  Library: {target_library}")
    console.print(f"  Window: last {days} days\n")

    try:
        status = plex_analysis.get_sonic_status(target_library, recent_days=days)
        # Same window definition as the service.
        cutoff = datetime.now() - timedelta(days=days)
        window_albums = [
            a
            for a in status.unanalyzed_albums
            if a.most_recent_added_at is not None and a.most_recent_added_at >= cutoff
        ]

        if status.recent_unanalyzed_tracks == 0:
            console.print(
                f"[green]✓ All {status.recent_tracks:,} tracks added in the last "
                f"{days} days already have sonic analysis.[/green]\n"
            )
            return

        console.print(
            f"Pending in window: [bold]{status.recent_unanalyzed_tracks:,}[/bold] "
            f"tracks across {len(window_albums)} albums "
            f"(of {status.recent_tracks:,} tracks added in the last {days} days)"
        )
        _album_table(window_albums)
        console.print(
            "\n[yellow]This triggers Plex's MusicAnalysis task, which processes "
            "Plex's entire pending backlog (CPU-heavy).[/yellow]"
        )
        if not typer.confirm("Continue?", default=False):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

        console.print()
        result = plex_analysis.refresh_sonic_analysis(
            target_library,
            days=days,
            wait_seconds=wait,
            on_poll=lambda now, before: console.print(
                f"  … pending in window: {now:,}/{before:,}", highlight=False
            ),
        )

        console.print("\n[bold]Refresh result[/bold]")
        console.print(
            f"  Analyzed this run: {result.analyzed_delta:,} tracks "
            f"({result.pending_tracks_before:,} → {result.pending_tracks_after:,} "
            f"pending) in {result.waited_seconds:.0f}s"
        )
        if result.activities_observed:
            console.print("  Activities observed:")
            for activity in result.activities_observed:
                console.print(f"    • {activity}")

        if result.completed:
            console.print(
                "\n[green]✓ Sonic analysis refreshed for the window. Run "
                "[bold]musicseed import-plex-sonic[/bold] to pull the new vectors "
                "into MusicSeed.[/green]\n"
            )
        else:
            if result.stall_detected:
                console.print(
                    "\n[yellow]⚠ Progress stalled: Plex could not analyze the "
                    "remaining albums (their files may be unreadable).[/yellow]"
                )
            else:
                console.print(
                    "\n[yellow]⚠ Wait budget elapsed; the Plex task keeps running "
                    "in the background.[/yellow]"
                )
            console.print(
                f"  Still pending: {result.pending_tracks_after:,} tracks across "
                f"{len(result.still_pending_albums)} albums:"
            )
            _album_table(result.still_pending_albums)
            console.print()
    except (ConfigurationError, NotFoundError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Sonic refresh failed: {e}")
        console.print(f"[red]✗ Sonic refresh failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the ``sonic-refresh`` command to the Typer app."""
    app.command("sonic-refresh")(sonic_refresh)
