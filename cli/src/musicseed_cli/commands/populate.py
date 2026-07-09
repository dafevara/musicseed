"""``populate`` command: recommend complementary tracks for a Plex playlist."""

from typing import Annotated, Optional

import typer

from musicseed.exceptions import ConfigurationError, MusicSeedError, NotFoundError
from musicseed.logging_config import get_logger

from musicseed_cli.console import console
from musicseed_cli.rendering import build_weights, print_recommendations_table


def populate(
    playlist_name: Annotated[
        str,
        typer.Option("--playlist", help="Existing Plex playlist name to populate"),
    ],
    method: Annotated[
        str,
        typer.Option(
            "--method",
            help="Recommendation strategy: 'average' (mean of playlist) or "
            "'frequency' (vote count across per-track seeds)",
        ),
    ] = "average",
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Number of tracks to add"),
    ] = 10,
    per_seed_limit: Annotated[
        int,
        typer.Option(
            "--per-seed-limit", help="Candidates gathered per track (frequency method only)"
        ),
    ] = 30,
    explain: Annotated[
        bool,
        typer.Option("--explain", help="Show component scores and vote sources"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Preview recommendations only, skip the Plex write and confirmation"
        ),
    ] = False,
    w_sonic: Annotated[float, typer.Option("--w-sonic", help="Sonic similarity weight")] = 0.30,
    w_popularity: Annotated[
        float, typer.Option("--w-popularity", help="Popularity proximity weight")
    ] = 0.15,
    w_style: Annotated[float, typer.Option("--w-style", help="Style alignment weight")] = 0.10,
    w_genre: Annotated[float, typer.Option("--w-genre", help="Genre alignment weight")] = 0.15,
    w_era: Annotated[float, typer.Option("--w-era", help="Era proximity weight")] = 0.05,
    w_novelty: Annotated[float, typer.Option("--w-novelty", help="Novelty weight")] = 0.10,
    year_min: Annotated[
        Optional[int], typer.Option("--year-min", help="Minimum release year")
    ] = None,
    year_max: Annotated[
        Optional[int], typer.Option("--year-max", help="Maximum release year")
    ] = None,
    artist_max: Annotated[int, typer.Option("--artist-max", help="Max tracks per artist")] = 3,
    min_score: Annotated[
        Optional[float],
        typer.Option("--min-score", help="Exclude recommendations below this score (0.0–1.0)"),
    ] = None,
) -> None:
    """Recommend complementary tracks for an existing Plex playlist, then add them."""
    from musicseed.services import populate as populate_service

    if method not in ("average", "frequency"):
        console.print("[red]Error: --method must be 'average' or 'frequency'[/red]")
        raise typer.Exit(1)

    if min_score is not None and not (0.0 <= min_score <= 1.0):
        console.print("[red]Error: --min-score must be between 0.0 and 1.0[/red]")
        raise typer.Exit(1)

    weights = build_weights(
        sonic=w_sonic,
        popularity=w_popularity,
        style=w_style,
        genre=w_genre,
        era=w_era,
        novelty=w_novelty,
    )

    console.print("\n[bold]Generating recommendations for approval[/bold]")
    console.print(f"  Playlist: {playlist_name}")
    console.print(f"  Method: {method}")
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
        preview = populate_service.get_populate_recommendations(
            playlist_name,
            method=method,
            limit=limit,
            per_seed_limit=per_seed_limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=artist_max,
            min_score=min_score,
        )
    except NotFoundError as e:
        console.print(f"[red]Recommendation failed: {e}[/red]")
        raise typer.Exit(1)
    except ConfigurationError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Recommendation failed: {e}")
        console.print(f"[red]✗ Recommendation failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]")
        raise typer.Exit(1)

    if not preview.recommendations:
        console.print("[yellow]No recommendations — playlist not modified.[/yellow]")
        raise typer.Exit(0)

    console.print(
        f"  Matched {preview.matched_track_count}/{preview.playlist_track_count} "
        "playlist tracks in the local library.\n"
    )
    print_recommendations_table(preview.recommendations, explain=explain)
    console.print(f"\n[green]{len(preview.recommendations)} tracks ready.[/green]\n")

    if dry_run:
        console.print("[dim]Dry run — playlist not modified.[/dim]\n")
        raise typer.Exit(0)

    if not typer.confirm(
        f"Add {len(preview.recommendations)} tracks to playlist '{playlist_name}' in Plex?",
        default=False,
    ):
        console.print("[dim]Cancelled.[/dim]\n")
        raise typer.Exit(0)

    try:
        result = populate_service.populate_playlist(
            playlist_name,
            method=method,
            limit=limit,
            per_seed_limit=per_seed_limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=artist_max,
            min_score=min_score,
        )
        console.print(
            f"\n[green]✓ Added {result.added_count} tracks to playlist "
            f"'{playlist_name}' in Plex.[/green]\n"
        )
    except ConfigurationError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except MusicSeedError as e:
        console.print(f"\n[red]✗ {e}[/red]\n")
        raise typer.Exit(1)
    except Exception as e:
        log = get_logger("cli")
        log.exception(f"Populating Plex playlist failed: {e}")
        console.print(f"\n[red]✗ Populating Plex playlist failed: {e}[/red]")
        console.print("[dim]Check logs/latest.log for details[/dim]\n")
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    app.command()(populate)
