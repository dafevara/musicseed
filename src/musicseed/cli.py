"""MusicSeed CLI interface."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import or_

from musicseed import __version__
from musicseed.config import get_config, load_config, set_config
from musicseed.db.session import create_indexes, ensure_schema, get_session, init_db
from musicseed.importers.plex import import_from_plex, import_plex_sonic_embeddings
from musicseed.logging_config import get_logger, parse_log_level, setup_logging

app = typer.Typer(
    name="musicseed",
    help="Music recommendation CLI for Plex - create playlists based on seed tracks.",
    no_args_is_help=True,
)
console = Console()


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
    config = get_config()

    console.print("\n[bold]Initializing database[/bold]")
    console.print(f"  Host: {config.database.host}:{config.database.port}")
    console.print(f"  Database: {config.database.name}\n")

    try:
        with console.status("[bold green]Creating tables..."):
            init_db()
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
    config = get_config()

    console.print("\n[bold]Optimizing database[/bold]")
    console.print(f"  Host: {config.database.host}:{config.database.port}")
    console.print(f"  Database: {config.database.name}\n")

    try:
        ensure_schema()
        with console.status("[bold green]Creating indexes..."):
            results = create_indexes()

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
    from musicseed.db.models import Album, Artist, Genre, Mood, PlayHistory, Style, Track

    config = get_config()

    console.print("\n[bold]MusicSeed Status[/bold]\n")

    # Database connection info
    config_table = Table(title="Configuration")
    config_table.add_column("Setting", style="cyan")
    config_table.add_column("Value", style="green")

    db_label = f"{config.database.host}:{config.database.port}/{config.database.name}"
    config_table.add_row("Database", db_label)
    config_table.add_row("Plex URL", config.plex.url)
    config_table.add_row("Plex DB", str(config.plex.db_path_expanded))
    config_table.add_row("Plex Library", config.plex.library)

    console.print(config_table)

    # Database statistics
    try:
        ensure_schema()
        with get_session() as session:
            artist_count = session.query(Artist).count()
            album_count = session.query(Album).count()
            track_count = session.query(Track).count()
            play_count = session.query(PlayHistory).count()

            # Enrichment stats
            tracks_with_mbid = session.query(Track).filter(Track.mbid.isnot(None)).count()
            tracks_with_spotify = (
                session.query(Track).filter(Track.spotify_id.isnot(None)).count()
            )
            spotify_attempted = (
                session.query(Track).filter(Track.spotify_matched.is_(True)).count()
            )
            tracks_with_embedding = (
                session.query(Track).filter(Track.embedding.isnot(None)).count()
            )
            embeddings_attempted = (
                session.query(Track).filter(Track.embedding_generated.is_(True)).count()
            )
            tracks_with_listenbrainz = (
                session.query(Track)
                .filter(
                    or_(
                        Track.listenbrainz_listen_count.isnot(None),
                        Track.listenbrainz_listener_count.isnot(None),
                    )
                )
                .count()
            )
            listenbrainz_attempted = (
                session.query(Track).filter(Track.listenbrainz_matched.is_(True)).count()
            )

            # Tag stats
            genre_count = session.query(Genre).count()
            mood_count = session.query(Mood).count()
            style_count = session.query(Style).count()

        stats_table = Table(title="Library Statistics")
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Count", style="green", justify="right")

        stats_table.add_row("Artists", f"{artist_count:,}")
        stats_table.add_row("Albums", f"{album_count:,}")
        stats_table.add_row("Tracks", f"{track_count:,}")
        stats_table.add_row("Play history entries", f"{play_count:,}")
        stats_table.add_row("Genres", f"{genre_count:,}")
        stats_table.add_row("Moods", f"{mood_count:,}")
        stats_table.add_row("Styles", f"{style_count:,}")

        console.print()
        console.print(stats_table)

        if track_count > 0:
            def pct(count: int, total: int) -> str:
                if total <= 0:
                    return "n/a"
                return f"{(count / total) * 100:.1f}%"

            enrichment_table = Table(title="Enrichment Status")
            enrichment_table.add_column("Source", style="cyan")
            enrichment_table.add_column("Eligible", style="blue", justify="right")
            enrichment_table.add_column("Attempted", style="magenta", justify="right")
            enrichment_table.add_column("Successful", style="green", justify="right")
            enrichment_table.add_column("Success Rate", style="yellow", justify="right")
            enrichment_table.add_column("Coverage", style="yellow", justify="right")

            enrichment_table.add_row(
                "MusicBrainz ID",
                f"{track_count:,}",
                "n/a",
                f"{tracks_with_mbid:,}",
                "n/a",
                pct(tracks_with_mbid, track_count),
            )
            enrichment_table.add_row(
                "Spotify",
                f"{track_count:,}",
                f"{spotify_attempted:,}",
                f"{tracks_with_spotify:,}",
                pct(tracks_with_spotify, spotify_attempted),
                pct(tracks_with_spotify, track_count),
            )

            enrichment_table.add_row(
                "Embeddings",
                f"{track_count:,}",
                f"{embeddings_attempted:,}",
                f"{tracks_with_embedding:,}",
                pct(tracks_with_embedding, embeddings_attempted),
                pct(tracks_with_embedding, track_count),
            )
            enrichment_table.add_row(
                "ListenBrainz",
                f"{tracks_with_mbid:,}",
                f"{listenbrainz_attempted:,}",
                f"{tracks_with_listenbrainz:,}",
                pct(tracks_with_listenbrainz, listenbrainz_attempted),
                pct(tracks_with_listenbrainz, track_count),
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
    config = get_config()

    db_path = plex_db or config.plex.db_path_expanded
    target_library = library or config.plex.library

    if not db_path.exists():
        console.print(f"[red]Error: Plex database not found at {db_path}[/red]")
        console.print("\nPlease specify the path with --plex-db or update your config file.")
        raise typer.Exit(1)

    console.print("\n[bold]Importing from Plex database[/bold]")
    console.print(f"  Database: {db_path}")
    console.print(f"  Library: {target_library}")
    console.print(f"  Mode: {'Full' if full else 'Incremental'}\n")

    try:
        with get_session() as session:
            imported = import_from_plex(
                session=session,
                plex_db_path=db_path,
                library_name=target_library,
                full_import=full,
            )

        console.print("\n[green]✓ Import completed![/green]")
        console.print(f"  Artists: {imported['artists']:,}")
        console.print(f"  Albums: {imported['albums']:,}")
        console.print(f"  Tracks: {imported['tracks']:,}")
        console.print(f"  Play history: {imported['play_history']:,}\n")
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
    config = get_config()

    db_path = plex_db or config.plex.db_path_expanded
    blobs_path = blobs_db or db_path.with_name(f"{db_path.stem}.blobs{db_path.suffix}")
    target_library = library or config.plex.library

    if not db_path.exists():
        console.print(f"[red]Error: Plex database not found at {db_path}[/red]")
        raise typer.Exit(1)
    if not blobs_path.exists():
        console.print(f"[red]Error: Plex blobs database not found at {blobs_path}[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Importing Plex sonic analysis[/bold]")
    console.print(f"  Database: {db_path}")
    console.print(f"  Blobs: {blobs_path}")
    console.print(f"  Library: {target_library}")
    console.print(f"  Mode: {'Overwrite' if overwrite else 'Missing only'}\n")

    try:
        ensure_schema()
        with get_session() as session:
            stats = import_plex_sonic_embeddings(
                session=session,
                plex_db_path=db_path,
                blobs_db_path=blobs_path,
                library_name=target_library,
                overwrite=overwrite,
            )

        console.print("\n[green]✓ Plex sonic import completed![/green]")
        console.print(f"  Available vectors: {stats['available']:,}")
        console.print(f"  Imported: {stats['imported']:,}")
        console.print(f"  Skipped: {stats['skipped']:,}")
        console.print(f"  Invalid Plex blobs: {stats['invalid']:,}")
        console.print(f"  Missing MusicSeed tracks: {stats['missing']:,}\n")
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
    import asyncio

    from musicseed.enrichers.pipeline import run_enrichment

    if source not in {"spotify", "listenbrainz"}:
        console.print(
            f"[red]Unknown source: {source}. Supported sources: spotify, listenbrainz.[/red]"
        )
        raise typer.Exit(1)

    config = get_config()

    if source == "spotify" and (
        not config.spotify.client_id or not config.spotify.client_secret
    ):
        console.print("[red]Spotify credentials not configured.[/red]")
        console.print("Add spotify.client_id and spotify.client_secret to your config file.")
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
        with get_session() as session:
            ensure_schema()
            stats = asyncio.run(
                run_enrichment(
                    session=session,
                    source=source,
                    client_id=config.spotify.client_id,
                    client_secret=config.spotify.client_secret,
                    batch_size=batch_size,
                    limit=limit,
                    artist=artist,
                    album=album,
                    unattempted_only=resume,
                    concurrency=concurrency,
                )
            )

        console.print("\n[green]✓ Enrichment completed![/green]")
        console.print(f"  Total processed: {stats.total:,}")
        matched_pct = stats.matched / max(stats.total, 1) * 100
        console.print(f"  Matched: {stats.matched:,} ({matched_pct:.1f}%)")
        console.print(f"  Unmatched: {stats.unmatched:,}")
        if stats.errors:
            console.print(f"  Errors: {stats.errors:,}")
        console.print()

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
    from musicseed.embeddings.pipeline import run_embedding_pipeline

    console.print(f"\n[bold]Generating embeddings with {model}[/bold]")

    try:
        with get_session() as session:
            stats = run_embedding_pipeline(
                session=session,
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
        typer.Option("--limit", "-n", help="Playlist length"),
    ] = 50,
    playlist: Annotated[
        Optional[str],
        typer.Option("--playlist", "-p", help="Plex playlist name"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Output to console only"),
    ] = False,
    explain: Annotated[
        bool,
        typer.Option("--explain", help="Show component scores and candidate sources"),
    ] = False,
    # Weights
    w_sonic: Annotated[
        float,
        typer.Option("--w-sonic", help="Sonic similarity weight"),
    ] = 0.30,
    w_popularity: Annotated[
        float,
        typer.Option("--w-popularity", help="Popularity proximity weight"),
    ] = 0.15,
    w_style: Annotated[
        float,
        typer.Option("--w-style", help="Style alignment weight"),
    ] = 0.10,
    w_genre: Annotated[
        float,
        typer.Option("--w-genre", help="Genre alignment weight"),
    ] = 0.15,
    w_era: Annotated[
        float,
        typer.Option("--w-era", help="Era proximity weight"),
    ] = 0.05,
    w_novelty: Annotated[
        float,
        typer.Option("--w-novelty", help="Novelty weight"),
    ] = 0.10,
    # Filters
    year_min: Annotated[
        Optional[int],
        typer.Option("--year-min", help="Minimum release year"),
    ] = None,
    year_max: Annotated[
        Optional[int],
        typer.Option("--year-max", help="Maximum release year"),
    ] = None,
    artist_max: Annotated[
        int,
        typer.Option("--artist-max", help="Max tracks per artist"),
    ] = 3,
) -> None:
    """Generate playlist recommendations from seed tracks."""
    from musicseed.recommender.playlist import recommend_tracks
    from musicseed.recommender.scoring import Weights, track_popularity_value

    def popularity_cell(track) -> str:
        """Best-available popularity on a 0-100 scale, matching scoring."""
        value = track_popularity_value(track)
        return f"{value:.0f}" if value is not None else ""

    if not seed and not seed_id:
        console.print("[red]Error: At least one --seed or --seed-id is required[/red]")
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
    console.print(f"  Playlist: {playlist or '(dry run)'}")
    console.print(
        "  Weights: "
        f"sonic={w_sonic}, popularity_proximity={w_popularity}, "
        f"style={w_style}, genre={w_genre}, era={w_era}, novelty={w_novelty}"
    )
    if year_min or year_max:
        console.print(f"  Year filter: {year_min or '...'} - {year_max or '...'}")
    console.print(f"  Max per artist: {artist_max}\n")

    try:
        with get_session() as session:
            seed_tracks, recommendations = recommend_tracks(
                session=session,
                seed_texts=seed,
                seed_ids=seed_id,
                limit=limit,
                weights=weights,
                year_min=year_min,
                year_max=year_max,
                max_tracks_per_artist=artist_max,
            )

            seed_table = Table(title="Resolved Seeds")
            seed_table.add_column("ID", justify="right", style="cyan")
            seed_table.add_column("Artist", style="green")
            seed_table.add_column("Track")
            seed_table.add_column("Year", justify="right")
            seed_table.add_column("Popularity", justify="right")
            for track in seed_tracks:
                seed_table.add_row(
                    str(track.id),
                    track.artist.name if track.artist else "",
                    track.title,
                    str(track.year or ""),
                    popularity_cell(track),
                )
            console.print(seed_table)

            result_table = Table(title="Recommendations")
            result_table.add_column("#", justify="right", style="cyan")
            result_table.add_column("Score", justify="right", style="green")
            result_table.add_column("Artist")
            result_table.add_column("Track")
            result_table.add_column("Year", justify="right")
            result_table.add_column("Popularity", justify="right")
            if explain:
                result_table.add_column("Components")
                result_table.add_column("Sources")

            for position, recommendation in enumerate(recommendations, start=1):
                track = recommendation.track
                score = recommendation.score
                row = [
                    str(position),
                    f"{score.total:.3f}",
                    track.artist.name if track.artist else "",
                    track.title,
                    str(track.year or ""),
                    popularity_cell(track),
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
                result_table.add_row(*row)

            console.print()
            console.print(result_table)
            console.print(f"\n[green]Generated {len(recommendations)} recommendations.[/green]")

            if playlist and not dry_run:
                console.print(
                    "[yellow]Plex playlist creation is not implemented yet; "
                    "recommendations were generated only.[/yellow]"
                )
            console.print()

    except ValueError as e:
        console.print(f"[red]Recommendation failed: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Recommendation failed: {e}")
        console.print(f"[red]✗ Recommendation failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
