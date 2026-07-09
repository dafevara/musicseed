"""``optimize-db`` command: create performance indexes."""

import typer
from rich.table import Table

from musicseed.config import get_config
from musicseed.logging_config import get_logger

from musicseed_cli.console import console


def optimize_database() -> None:
    """Create database indexes for import, enrichment, and recommendation performance."""
    from musicseed.services import library as library_service

    config = get_config()

    console.print("\n[bold]Optimizing database[/bold]")
    console.print(f"  Host: {config.database.host}:{config.database.port}")
    console.print(f"  Database: {config.database.name}\n")

    try:
        with console.status("[bold green]Creating indexes..."):
            results = library_service.optimize_database()

        table = Table(title="Index Creation Results")
        table.add_column("Index", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Error", style="red")

        failures = 0
        for result in results:
            if result.success:
                table.add_row(result.name, "ok", "")
            else:
                failures += 1
                table.add_row(result.name, "failed", result.error or "")

        console.print(table)
        if failures:
            console.print(f"\n[yellow]Completed with {failures} index error(s).[/yellow]")
            console.print("[dim]Check logs/latest.log for details if needed.[/dim]\n")
            raise typer.Exit(1)

        console.print("\n[green]✓ Database indexes created successfully.[/green]\n")
    except typer.Exit:
        raise
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Database optimization failed: {e}")
        console.print(f"[red]✗ Database optimization failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    app.command("optimize-db")(optimize_database)
