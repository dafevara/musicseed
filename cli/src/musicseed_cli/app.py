"""MusicSeed CLI application: Typer app assembly and global options."""

from pathlib import Path
from typing import Annotated, Optional

import typer

from musicseed import __version__
from musicseed.config import get_config, load_config, set_config
from musicseed.logging_config import parse_log_level, setup_logging

from musicseed_cli.commands import register_all
from musicseed_cli.console import console

app = typer.Typer(
    name="musicseed",
    help="Music recommendation CLI for Plex - create playlists based on seed tracks.",
    no_args_is_help=True,
)


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


register_all(app)


if __name__ == "__main__":
    app()
