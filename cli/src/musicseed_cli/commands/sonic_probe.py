"""``sonic-probe`` command: inspect and test Plex sonic analysis coverage."""

import time
from typing import Annotated, Optional

import typer
from rich.table import Table

from musicseed.config import get_config
from musicseed.exceptions import ConfigurationError, NotFoundError
from musicseed.logging_config import get_logger

from musicseed_cli.console import console


def _print_status(result) -> None:
    pct = (
        100.0 * result.analyzed_tracks / result.total_tracks
        if result.total_tracks
        else 0.0
    )
    console.print(f"  Section ID: {result.section_id}")
    console.print(f"  Total tracks: {result.total_tracks:,}")
    console.print(
        f"  Sonically analyzed: {result.analyzed_tracks:,} ({pct:.1f}%)"
    )
    console.print(f"  Not analyzed: {result.unanalyzed_tracks:,}")
    console.print(
        f"  Added in last {result.recent_days} days: {result.recent_tracks:,} "
        f"({result.recent_analyzed_tracks:,} analyzed, "
        f"{result.recent_unanalyzed_tracks:,} pending)"
    )

    if result.unanalyzed_albums:
        console.print(
            f"\n[bold]Albums with unanalyzed tracks "
            f"({len(result.unanalyzed_albums):,}, most recent first)[/bold]"
        )
        table = Table(show_header=True, header_style="bold")
        table.add_column("Album Key", style="dim")
        table.add_column("Artist")
        table.add_column("Album")
        table.add_column("Pending", justify="right")
        table.add_column("Added")
        for album in result.unanalyzed_albums[:15]:
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
        if len(result.unanalyzed_albums) > 15:
            console.print(f"[dim]  … and {len(result.unanalyzed_albums) - 15} more[/dim]")


def sonic_probe(
    library: Annotated[
        Optional[str],
        typer.Option("--library", "-l", help="Plex library name (default: config)"),
    ] = None,
    days: Annotated[
        int,
        typer.Option("--days", help="Recent additions window in days"),
    ] = 7,
    trigger: Annotated[
        bool,
        typer.Option(
            "--trigger",
            help="Trigger Plex analysis on one unanalyzed album and watch whether "
            "sonic analysis follows",
        ),
    ] = False,
    trigger_butler: Annotated[
        bool,
        typer.Option(
            "--trigger-butler",
            help="Trigger the Plex 'MusicAnalysis' Butler task (processes ALL pending "
            "albums, CPU-heavy) and watch one album for sonic analysis",
        ),
    ] = False,
    album_key: Annotated[
        Optional[str],
        typer.Option(
            "--album-key",
            help="Album ratingKey to analyze/watch with --trigger/--trigger-butler",
        ),
    ] = None,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Refresh the album's metadata first (re-reads files, clears "
            "failed-analysis state) before triggering",
        ),
    ] = False,
    refresh_wait: Annotated[
        int,
        typer.Option(
            "--refresh-wait",
            help="Seconds to let Plex re-scan after --refresh before triggering",
        ),
    ] = 60,
    wait: Annotated[
        int,
        typer.Option("--wait", help="Seconds to watch for sonic analysis after --trigger"),
    ] = 120,
) -> None:
    """Probe Plex sonic analysis coverage for a music library.

    Without flags this is read-only: it reports how many tracks Plex has
    sonically analyzed (overall and recently added) and lists the albums
    still pending. --trigger / --trigger-butler ask Plex to analyze one
    album and watch whether sonic analysis follows; both ask for
    confirmation first.
    """
    from musicseed.services import plex_analysis

    config = get_config()
    target_library = library or config.plex.library

    console.print("\n[bold]Plex sonic analysis probe[/bold]")
    console.print(f"  Server: {config.plex.url}")
    console.print(f"  Library: {target_library}\n")

    try:
        if trigger and trigger_butler:
            console.print("[red]Error: use either --trigger or --trigger-butler, not both.[/red]")
            raise typer.Exit(1)
        if refresh and not (trigger or trigger_butler):
            console.print("[red]Error: --refresh requires --trigger or --trigger-butler.[/red]")
            raise typer.Exit(1)

        if not trigger and not trigger_butler:
            result = plex_analysis.get_sonic_status(target_library, recent_days=days)
            _print_status(result)
            console.print(
                "\n[dim]Run with --trigger to test whether the Plex analyze "
                "endpoint kicks off sonic analysis on your server, or "
                "--trigger-butler to run the MusicAnalysis Butler task.[/dim]\n"
            )
            return

        if trigger_butler:
            console.print(
                "[yellow]This will run the Plex 'MusicAnalysis' Butler task, which "
                "processes ALL albums pending sonic analysis (CPU-heavy, keeps "
                "running after this probe finishes).[/yellow]"
            )
        else:
            console.print(
                "[yellow]This will ask Plex to analyze an album in your library.[/yellow]"
            )
        if not typer.confirm("Continue?", default=False):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

        if refresh:
            if album_key is None:
                status = plex_analysis.get_sonic_status(target_library, recent_days=days)
                if not status.unanalyzed_albums:
                    console.print("[green]No unanalyzed albums found.[/green]")
                    raise typer.Exit(0)
                album_key = status.unanalyzed_albums[0].rating_key
            console.print(
                f"Refreshing album {album_key} metadata, then waiting "
                f"{refresh_wait}s for Plex to re-scan…"
            )
            plex_analysis.refresh_album(album_key)
            time.sleep(refresh_wait)

        if trigger_butler:
            probe = plex_analysis.probe_butler_trigger(
                album_key,
                target_library,
                wait_seconds=wait,
            )
        else:
            probe = plex_analysis.probe_sonic_trigger(
                album_key,
                target_library,
                wait_seconds=wait,
            )
        console.print(f"\n[bold]Trigger probe result ({probe.trigger_method})[/bold]")
        console.print(
            f"  Album: {probe.artist_title or '?'} — {probe.album_title or '?'} "
            f"(key={probe.album_rating_key})"
        )
        console.print(f"  Tracks: {probe.track_count}")
        console.print(
            f"  Analyzed before: {probe.analyzed_before} → "
            f"after {probe.waited_seconds:.0f}s: {probe.analyzed_after}"
        )
        if probe.activities_observed:
            console.print("  Activities observed:")
            for activity in probe.activities_observed:
                console.print(f"    • {activity}")
        else:
            console.print("  Activities observed: none")

        if probe.sonic_triggered:
            console.print(
                "\n[green]✓ Sonic analysis followed the analyze trigger — "
                "the endpoint works on this server.[/green]\n"
            )
        else:
            console.print(
                "\n[yellow]⚠ No sonic analysis detected within "
                f"{probe.waited_seconds:.0f}s of the trigger. Sonic analysis may be "
                "Butler-scheduled only on this server.[/yellow]\n"
            )
    except (ConfigurationError, NotFoundError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Sonic probe failed: {e}")
        console.print(f"[red]✗ Sonic probe failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the ``sonic-probe`` command to the Typer app."""
    app.command("sonic-probe")(sonic_probe)
