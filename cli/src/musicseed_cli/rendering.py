"""Shared rendering helpers for recommendation output."""

from musicseed.recommender.scoring import Weights
from rich.table import Table

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
    """Assemble a Weights object from individual scoring weights.

    Args:
        sonic: sonic similarity weight.
        popularity: popularity proximity weight.
        style: style alignment weight.
        genre: genre alignment weight.
        era: era proximity weight.
        novelty: novelty weight.

    Returns:
        The assembled ``Weights``; normalization happens at scoring time.
    """
    return Weights(
        sonic=sonic,
        popularity=popularity,
        style=style,
        genre=genre,
        era=era,
        novelty=novelty,
    )


def popularity_cell(track) -> str:
    """Format a track's popularity for a table cell ("" when unknown).

    Args:
        track: a Track ORM object.

    Returns:
        The popularity value (0-100 scale) rounded to an integer string, or
        an empty string when the track has no popularity data.
    """
    from musicseed.recommender.scoring import track_popularity_value

    value = track_popularity_value(track)
    return f"{value:.0f}" if value is not None else ""


def print_seed_table(seed_tracks: list) -> None:
    """Render the resolved seed tracks as a Rich table.

    Args:
        seed_tracks: Track ORM objects with artist eagerly loaded.
    """
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
    """Render recommendations as a Rich table.

    Args:
        recommendations: ``Recommendation`` objects (track, score breakdown,
            candidate sources).
        explain: also show the per-signal component scores and the candidate
            sources that produced each recommendation.
    """
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
