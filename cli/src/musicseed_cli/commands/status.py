"""``status`` command: show library statistics and enrichment status."""

import typer
from rich.table import Table

from musicseed_cli.console import console


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
                "Plex sonic",
                f"{stat.track_count:,}",
                "n/a",
                f"{e.tracks_with_sonic:,}",
                "n/a",
                pct(e.tracks_with_sonic, stat.track_count),
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


def register(app: typer.Typer) -> None:
    app.command()(status)
