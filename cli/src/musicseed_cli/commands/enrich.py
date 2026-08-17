"""``enrich`` command: enrich tracks with external metadata."""

from typing import Annotated, Optional

import typer
from musicseed.exceptions import ConfigurationError
from musicseed.logging_config import get_logger

from musicseed_cli.console import console


def enrich(
    source: Annotated[
        str,
        typer.Option("--source", "-s", help="Enrichment source"),
    ] = "listenbrainz",
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", "-b", help="Tracks per batch"),
    ] = 50,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", "-n", help="Max tracks to enrich"),
    ] = None,
    artist: Annotated[
        Optional[str],
        typer.Option("--artist", help="Only enrich matching artist names; supports * and ?"),
    ] = None,
    album: Annotated[
        Optional[str],
        typer.Option("--album", help="Only enrich matching album titles; supports * and ?"),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume", "-r", help="Resume: skip already attempted tracks"),
    ] = False,
    concurrency: Annotated[
        int,
        typer.Option("--concurrency", help="Concurrent async requests"),
    ] = 5,
) -> None:
    """Enrich tracks with external metadata.

    Fetches popularity and related metadata from ListenBrainz (default,
    requires a ListenBrainz user token — get one free at
    https://listenbrainz.org/settings/) or Spotify (requires configured
    client credentials). Use --resume to skip tracks that were already
    attempted.
    """
    from musicseed.services import enrichment as enrichment_service

    if source not in {"spotify", "listenbrainz"}:
        console.print(
            f"[red]Unknown source: {source}. Supported sources: spotify, listenbrainz.[/red]"
        )
        raise typer.Exit(1)

    console.print(f"\n[bold]Enriching tracks from {source}[/bold]")
    console.print(f"  Batch size: {batch_size}")
    console.print(f"  Concurrency: {concurrency}")
    console.print(f"  Limit: {limit or 'all'}")
    if artist:
        console.print(f"  Artist filter: {artist}")
    if album:
        console.print(f"  Album filter: {album}")
    console.print(f"  Resume mode: {resume}\n")

    try:
        stats = enrichment_service.enrich_tracks(
            source=source,
            batch_size=batch_size,
            limit=limit,
            artist=artist,
            album=album,
            resume=resume,
            concurrency=concurrency,
        )
        console.print("\n[green]✓ Enrichment completed![/green]")
        console.print(f"  Total processed: {stats.total:,}")
        matched_pct = stats.matched / max(stats.total, 1) * 100
        console.print(f"  Matched: {stats.matched:,} ({matched_pct:.1f}%)")
        console.print(f"  Unmatched: {stats.unmatched:,}")
        if stats.errors:
            console.print(f"  Errors: {stats.errors:,}")
        console.print()
    except ConfigurationError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Enrichment failed: {e}")
        console.print(f"[red]✗ Enrichment failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Attach the ``enrich`` command to the Typer app."""
    app.command()(enrich)
