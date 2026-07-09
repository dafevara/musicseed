"""``init-db`` command: initialize the database schema."""

import typer

from musicseed.config import get_config

from musicseed_cli.console import console


def init_database() -> None:
    """Initialize the database schema (creates tables and extensions)."""
    from musicseed.services import library as library_service

    config = get_config()

    console.print("\n[bold]Initializing database[/bold]")
    console.print(f"  Host: {config.database.host}:{config.database.port}")
    console.print(f"  Database: {config.database.name}\n")

    try:
        with console.status("[bold green]Creating tables..."):
            library_service.initialize_database()
        console.print("[green]✓ Database initialized successfully![/green]")
        console.print("  - pgvector extension enabled")
        console.print("  - All tables created\n")
    except Exception as e:
        console.print(f"[red]✗ Failed to initialize database: {e}[/red]")
        console.print("\nMake sure PostgreSQL is running:")
        console.print("  docker-compose up -d\n")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    app.command("init-db")(init_database)
