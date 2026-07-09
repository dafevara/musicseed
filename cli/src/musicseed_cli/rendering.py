"""Shared rendering helpers for recommendation output."""

from rich.table import Table

from musicseed.recommender.scoring import Weights

from musicseed_cli.console import console


def build_weights(
    *,
    sonic: float,
    popularity: float,
    style: float,
    genre: float,
    era: float,
    novelty: float,
) -> Weights:
    """Assemble a Weights object from individual scoring weights."""
    return Weights(
        sonic=sonic,
        popularity=popularity,
        style=style,
        genre=genre,
        era=era,
        novelty=novelty,
    )


def popularity_cell(track) -> str:
    from musicseed.recommender.scoring import track_popularity_value

    value = track_popularity_value(track)
    return f"{value:.0f}" if value is not None else ""


def print_seed_table(seed_tracks: list) -> None:
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
            popularity_cell(track),
        )
    console.print(table)


def print_recommendations_table(recommendations: list, *, explain: bool) -> None:
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
        table.add_row(*row)
    console.print()
    console.print(table)
