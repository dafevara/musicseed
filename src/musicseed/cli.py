"""MusicSeed CLI interface."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from musicseed import __version__
from musicseed.config import get_config, load_config, set_config
from musicseed.exceptions import ConfigurationError, MusicSeedError, NotFoundError
from musicseed.logging_config import get_logger, parse_log_level, setup_logging
from musicseed.recommender.scoring import Weights

app = typer.Typer(
    name="musicseed",
    help="Music recommendation CLI for Plex - create playlists based on seed tracks.",
    no_args_is_help=True,
)
console = Console()


def _popularity_cell(track) -> str:
    from musicseed.recommender.scoring import track_popularity_value
    value = track_popularity_value(track)
    return f"{value:.0f}" if value is not None else ""


def _print_seed_table(seed_tracks: list) -> None:
    table = Table(title="Resolved Seeds")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("Artist", style="green")
    table.add_column("Track")
    table.add_column("Year", justify="right")
    table.add_column("Popularity", justify="right")
    for track in seed_tracks:
        table.add_row(
            str(track.id),
            track.artist.name if track.artist else "",
            track.title,
            str(track.year or ""),
            _popularity_cell(track),
        )
    console.print(table)


def _print_recommendations_table(recommendations: list, *, explain: bool) -> None:
    table = Table(title="Recommendations")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Artist")
    table.add_column("Track")
    table.add_column("Year", justify="right")
    table.add_column("Popularity", justify="right")
    if explain:
        table.add_column("Components")
        table.add_column("Sources")
    for position, recommendation in enumerate(recommendations, start=1):
        track = recommendation.track
        score = recommendation.score
        row = [
            str(position),
            f"{score.total:.3f}",
            track.artist.name if track.artist else "",
            track.title,
            str(track.year or ""),
            _popularity_cell(track),
        ]
        if explain:
            row.extend([
                (
                    f"sonic={score.sonic:.2f} pop={score.popularity:.2f} "
                    f"style={score.style:.2f} genre={score.genre:.2f} "
                    f"era={score.era:.2f} novelty={score.novelty:.2f}"
                ),
                ",".join(recommendation.sources),
            ])
        table.add_row(*row)
    console.print()
    console.print(table)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"MusicSeed version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-v", callback=version_callback, is_eager=True),
    ] = None,
    config_file: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file"),
    ] = None,
    log_level: Annotated[
        Optional[str],
        typer.Option("--log-level", help="File logging level: DEBUG, INFO, WARNING, ERROR"),
    ] = None,
    log_console: Annotated[
        bool,
        typer.Option("--log-console", help="Also print logs to stderr"),
    ] = False,
    log_console_level: Annotated[
        Optional[str],
        typer.Option("--log-console-level", help="Console logging level"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Shortcut for --log-level DEBUG"),
    ] = False,
) -> None:
    """MusicSeed - Music recommendation CLI for Plex."""
    if config_file:
        config = load_config(config_file)
        set_config(config)
    else:
        config = get_config()

    selected_log_level = "DEBUG" if verbose else (log_level or config.logging.level)
    selected_console_level = log_console_level or config.logging.console_level
    console_logging = log_console or config.logging.console
    try:
        setup_logging(
            level=parse_log_level(selected_log_level),
            console=console_logging,
            console_level=parse_log_level(selected_console_level),
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@app.command("init-db")
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


@app.command("optimize-db")
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


@app.command()
def status() -> None:
    """Show library statistics and enrichment status."""
    from musicseed.services import library as library_service

    console.print("\n[bold]MusicSeed Status[/bold]\n")

    try:
        stat = library_service.get_status()

        config_table = Table(title="Configuration")
        config_table.add_column("Setting", style="cyan")
        config_table.add_column("Value", style="green")
        config_table.add_row("Database", f"{stat.db_host}:{stat.db_port}/{stat.db_name}")
        config_table.add_row("Plex URL", stat.plex_url)
        config_table.add_row("Plex DB", stat.plex_db)
        config_table.add_row("Plex Library", stat.plex_library)
        console.print(config_table)

        stats_table = Table(title="Library Statistics")
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Count", style="green", justify="right")
        stats_table.add_row("Artists", f"{stat.artist_count:,}")
        stats_table.add_row("Albums", f"{stat.album_count:,}")
        stats_table.add_row("Tracks", f"{stat.track_count:,}")
        stats_table.add_row("Play history entries", f"{stat.play_count:,}")
        stats_table.add_row("Genres", f"{stat.genre_count:,}")
        stats_table.add_row("Moods", f"{stat.mood_count:,}")
        stats_table.add_row("Styles", f"{stat.style_count:,}")

        console.print()
        console.print(stats_table)

        if stat.track_count > 0:
            def pct(count: int, total: int) -> str:
                if total <= 0:
                    return "n/a"
                return f"{(count / total) * 100:.1f}%"

            e = stat.enrichment
            enrichment_table = Table(title="Enrichment Status")
            enrichment_table.add_column("Source", style="cyan")
            enrichment_table.add_column("Eligible", style="blue", justify="right")
            enrichment_table.add_column("Attempted", style="magenta", justify="right")
            enrichment_table.add_column("Successful", style="green", justify="right")
            enrichment_table.add_column("Success Rate", style="yellow", justify="right")
            enrichment_table.add_column("Coverage", style="yellow", justify="right")

            enrichment_table.add_row(
                "MusicBrainz ID",
                f"{stat.track_count:,}",
                "n/a",
                f"{e.tracks_with_mbid:,}",
                "n/a",
                pct(e.tracks_with_mbid, stat.track_count),
            )
            enrichment_table.add_row(
                "Spotify",
                f"{stat.track_count:,}",
                f"{e.spotify_attempted:,}",
                f"{e.tracks_with_spotify:,}",
                pct(e.tracks_with_spotify, e.spotify_attempted),
                pct(e.tracks_with_spotify, stat.track_count),
            )
            enrichment_table.add_row(
                "Embeddings",
                f"{stat.track_count:,}",
                f"{e.embeddings_attempted:,}",
                f"{e.tracks_with_embedding:,}",
                pct(e.tracks_with_embedding, e.embeddings_attempted),
                pct(e.tracks_with_embedding, stat.track_count),
            )
            enrichment_table.add_row(
                "ListenBrainz",
                f"{e.tracks_with_mbid:,}",
                f"{e.listenbrainz_attempted:,}",
                f"{e.tracks_with_listenbrainz:,}",
                pct(e.tracks_with_listenbrainz, e.listenbrainz_attempted),
                pct(e.tracks_with_listenbrainz, stat.track_count),
            )

            console.print()
            console.print(enrichment_table)
        console.print()

    except Exception as e:
        console.print(f"\n[yellow]Could not connect to database: {e}[/yellow]")
        console.print("Run 'musicseed init-db' to initialize the database.\n")


@app.command("import")
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
    """Import metadata from Plex database."""
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


@app.command("import-plex-sonic")
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


@app.command()
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
    """Enrich tracks with external metadata."""
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


@app.command()
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


@app.command()
def recommend(
    seed: Annotated[
        Optional[list[str]],
        typer.Option("--seed", "-s", help="Seed track (Artist - Title)"),
    ] = None,
    seed_id: Annotated[
        Optional[list[int]],
        typer.Option("--seed-id", help="Seed track by database ID"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Number of recommendations to return"),
    ] = 50,
    explain: Annotated[
        bool,
        typer.Option("--explain", help="Show component scores and candidate sources"),
    ] = False,
    w_sonic: Annotated[float, typer.Option("--w-sonic", help="Sonic similarity weight")] = 0.30,
    w_popularity: Annotated[float, typer.Option("--w-popularity", help="Popularity proximity weight")] = 0.15,
    w_style: Annotated[float, typer.Option("--w-style", help="Style alignment weight")] = 0.10,
    w_genre: Annotated[float, typer.Option("--w-genre", help="Genre alignment weight")] = 0.15,
    w_era: Annotated[float, typer.Option("--w-era", help="Era proximity weight")] = 0.05,
    w_novelty: Annotated[float, typer.Option("--w-novelty", help="Novelty weight")] = 0.10,
    year_min: Annotated[Optional[int], typer.Option("--year-min", help="Minimum release year")] = None,
    year_max: Annotated[Optional[int], typer.Option("--year-max", help="Maximum release year")] = None,
    artist_max: Annotated[int, typer.Option("--artist-max", help="Max tracks per artist")] = 3,
    min_score: Annotated[
        Optional[float],
        typer.Option("--min-score", help="Exclude recommendations below this score (0.0–1.0)"),
    ] = None,
) -> None:
    """Preview recommendations from seed tracks without writing to Plex."""
    from musicseed.services import recommend as recommend_service

    if not seed and not seed_id:
        console.print("[red]Error: At least one --seed or --seed-id is required[/red]")
        raise typer.Exit(1)

    if min_score is not None and not (0.0 <= min_score <= 1.0):
        console.print("[red]Error: --min-score must be between 0.0 and 1.0[/red]")
        raise typer.Exit(1)

    weights = Weights(
        sonic=w_sonic,
        popularity=w_popularity,
        style=w_style,
        genre=w_genre,
        era=w_era,
        novelty=w_novelty,
    )

    console.print("\n[bold]Generating recommendations[/bold]")
    if seed:
        console.print(f"  Seeds: {', '.join(seed)}")
    if seed_id:
        console.print(f"  Seed IDs: {', '.join(map(str, seed_id))}")
    console.print(f"  Limit: {limit}")
    console.print(
        "  Weights: "
        f"sonic={w_sonic}, popularity_proximity={w_popularity}, "
        f"style={w_style}, genre={w_genre}, era={w_era}, novelty={w_novelty}"
    )
    if year_min or year_max:
        console.print(f"  Year filter: {year_min or '...'} - {year_max or '...'}")
    if min_score is not None:
        console.print(f"  Min score: {min_score}")
    console.print(f"  Max per artist: {artist_max}\n")

    try:
        result = recommend_service.get_recommendations(
            seed_texts=seed,
            seed_ids=seed_id,
            limit=limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=artist_max,
            min_score=min_score,
        )
        _print_seed_table(result.seed_tracks)
        _print_recommendations_table(result.recommendations, explain=explain)
        console.print(f"\n[green]Generated {len(result.recommendations)} recommendations.[/green]\n")
    except NotFoundError as e:
        console.print(f"[red]Recommendation failed: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Recommendation failed: {e}")
        console.print(f"[red]✗ Recommendation failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


@app.command()
def playlist(
    name: Annotated[
        str,
        typer.Option("--name", help="Plex playlist name (must be unique in Plex)"),
    ],
    seed: Annotated[
        Optional[list[str]],
        typer.Option("--seed", "-s", help="Seed track (Artist - Title)"),
    ] = None,
    seed_id: Annotated[
        Optional[list[int]],
        typer.Option("--seed-id", help="Seed track by database ID"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Number of tracks in the playlist"),
    ] = 50,
    explain: Annotated[
        bool,
        typer.Option("--explain", help="Show component scores and candidate sources"),
    ] = False,
    w_sonic: Annotated[float, typer.Option("--w-sonic", help="Sonic similarity weight")] = 0.30,
    w_popularity: Annotated[float, typer.Option("--w-popularity", help="Popularity proximity weight")] = 0.15,
    w_style: Annotated[float, typer.Option("--w-style", help="Style alignment weight")] = 0.10,
    w_genre: Annotated[float, typer.Option("--w-genre", help="Genre alignment weight")] = 0.15,
    w_era: Annotated[float, typer.Option("--w-era", help="Era proximity weight")] = 0.05,
    w_novelty: Annotated[float, typer.Option("--w-novelty", help="Novelty weight")] = 0.10,
    year_min: Annotated[Optional[int], typer.Option("--year-min", help="Minimum release year")] = None,
    year_max: Annotated[Optional[int], typer.Option("--year-max", help="Maximum release year")] = None,
    artist_max: Annotated[int, typer.Option("--artist-max", help="Max tracks per artist")] = 3,
    min_score: Annotated[
        Optional[float],
        typer.Option("--min-score", help="Exclude recommendations below this score (0.0–1.0)"),
    ] = None,
) -> None:
    """Generate recommendations, prompt for approval, then create a Plex playlist."""
    from musicseed.services import recommend as recommend_service

    if not seed and not seed_id:
        console.print("[red]Error: At least one --seed or --seed-id is required[/red]")
        raise typer.Exit(1)

    if min_score is not None and not (0.0 <= min_score <= 1.0):
        console.print("[red]Error: --min-score must be between 0.0 and 1.0[/red]")
        raise typer.Exit(1)

    weights = Weights(
        sonic=w_sonic,
        popularity=w_popularity,
        style=w_style,
        genre=w_genre,
        era=w_era,
        novelty=w_novelty,
    )

    console.print("\n[bold]Generating recommendations for approval[/bold]")
    if seed:
        console.print(f"  Seeds: {', '.join(seed)}")
    if seed_id:
        console.print(f"  Seed IDs: {', '.join(map(str, seed_id))}")
    console.print(f"  Playlist name: {name}")
    console.print(f"  Limit: {limit}")
    console.print(
        "  Weights: "
        f"sonic={w_sonic}, popularity_proximity={w_popularity}, "
        f"style={w_style}, genre={w_genre}, era={w_era}, novelty={w_novelty}"
    )
    if year_min or year_max:
        console.print(f"  Year filter: {year_min or '...'} - {year_max or '...'}")
    if min_score is not None:
        console.print(f"  Min score: {min_score}")
    console.print(f"  Max per artist: {artist_max}\n")

    try:
        rec_result = recommend_service.get_recommendations(
            seed_texts=seed,
            seed_ids=seed_id,
            limit=limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=artist_max,
            min_score=min_score,
        )
    except NotFoundError as e:
        console.print(f"[red]Recommendation failed: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Recommendation failed: {e}")
        console.print(f"[red]✗ Recommendation failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)

    if not rec_result.recommendations:
        console.print("[yellow]No recommendations — playlist not created.[/yellow]")
        raise typer.Exit(0)

    _print_seed_table(rec_result.seed_tracks)
    _print_recommendations_table(rec_result.recommendations, explain=explain)
    console.print(f"\n[green]{len(rec_result.recommendations)} tracks ready.[/green]\n")

    if not typer.confirm(f"Create playlist '{name}' in Plex?", default=False):
        console.print("[dim]Cancelled.[/dim]\n")
        raise typer.Exit(0)

    try:
        plex_result = recommend_service.create_playlist(
            name,
            seed_texts=seed,
            seed_ids=seed_id,
            limit=limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=artist_max,
            min_score=min_score,
        )
        total = len(plex_result.seed_tracks) + len(plex_result.recommendations)
        console.print(
            f"\n[green]✓ Playlist '{plex_result.playlist.title}' created in Plex "
            f"({total} tracks).[/green]\n"
        )
    except ConfigurationError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except MusicSeedError as e:
        console.print(f"\n[red]✗ {e}[/red]\n")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Plex playlist creation failed: {e}")
        console.print(f"\n[red]✗ Plex playlist creation failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]\n")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
