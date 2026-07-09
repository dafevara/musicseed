"""``embed`` command: generate audio embeddings for tracks."""

from typing import Annotated, Optional

import typer

from musicseed.logging_config import get_logger

from musicseed_cli.console import console


def embed(
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Embedding model (essentia or simple)"),
    ] = "essentia",
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", "-b", help="Tracks per batch"),
    ] = 10,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", "-n", help="Max tracks to process"),
    ] = None,
    missing_only: Annotated[
        bool,
        typer.Option("--missing-only", help="Only process tracks without embeddings"),
    ] = True,
    workers: Annotated[
        int,
        typer.Option("--workers", "-w", help="Parallel workers"),
    ] = 4,
) -> None:
    """Generate audio embeddings for tracks."""
    from musicseed.services import enrichment as enrichment_service

    console.print(f"\n[bold]Generating embeddings with {model}[/bold]")

    try:
        stats = enrichment_service.generate_embeddings(
            model=model,
            batch_size=batch_size,
            limit=limit,
            missing_only=missing_only,
            workers=workers,
        )
        console.print("\n[green]✓ Embedding generation completed![/green]")
        console.print(f"  Total processed: {stats.total:,}")
        generated_pct = stats.generated / max(stats.total, 1) * 100
        console.print(f"  Generated: {stats.generated:,} ({generated_pct:.1f}%)")
        console.print(f"  Skipped: {stats.skipped:,}")
        if stats.errors:
            console.print(f"  Errors: {stats.errors:,}")
        console.print()
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Embedding generation failed: {e}")
        console.print(f"[red]✗ Embedding generation failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    app.command()(embed)
