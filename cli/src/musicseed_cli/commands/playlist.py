"""``playlist`` command: recommend, confirm, then create a Plex playlist."""

from typing import Annotated, Optional

import typer
from musicseed.exceptions import ConfigurationError, MusicSeedError, NotFoundError
from musicseed.logging_config import get_logger

from musicseed_cli.console import console
from musicseed_cli.rendering import (
    build_weights,
    print_recommendations_table,
    print_seed_table,
)


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
    """Generate recommendations, prompt for approval, then create a Plex playlist.

    Shows the resolved seeds and recommended tracks first; the Plex playlist
    is only created after you confirm. The playlist contains the seed tracks
    followed by the approved recommendations.
    """
    from musicseed.services import recommend as recommend_service

    if not seed and not seed_id:
        console.print("[red]Error: At least one --seed or --seed-id is required[/red]")
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

    print_seed_table(rec_result.seed_tracks)
    print_recommendations_table(rec_result.recommendations, explain=explain)
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


def register(app: typer.Typer) -> None:
    """Attach the ``playlist`` command to the Typer app."""
    app.command()(playlist)
