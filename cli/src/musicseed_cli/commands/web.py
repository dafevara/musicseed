"""``web`` command: start the local web UI and open it in the browser."""

import socket
import webbrowser

import typer

from musicseed_cli.console import console

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8788


def web(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        help="Interface to bind. Loopback by default; only choose another to "
        "deliberately expose the UI (e.g. 0.0.0.0 for LAN access).",
    ),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="Port to listen on."),
    no_open: bool = typer.Option(
        False, "--no-open", help="Do not open the browser automatically."
    ),
) -> None:
    """Start the local MusicSeed web UI and open it in your browser."""
    from musicseed_web.server import serve

    url = f"http://{_display_host(host)}:{port}"

    if _port_in_use(host, port):
        console.print(f"\n[red]Cannot start the web UI: {host}:{port} is already in use.[/red]")
        console.print(
            "Pass [bold]--port[/bold] to choose a different port, "
            f"e.g. [bold]musicseed web --port {port + 1}[/bold]\n"
        )
        raise typer.Exit(1)

    console.print(f"\n[bold]MusicSeed web UI[/bold] at [cyan]{url}[/cyan]")
    console.print("Press [bold]Ctrl+C[/bold] to stop.\n")

    def open_browser() -> None:
        if no_open:
            return
        console.print(f"Opening {url} in your browser…")
        webbrowser.open(url)

    try:
        serve(host=host, port=port, on_started=open_browser)
    except OSError as e:
        console.print(f"\n[red]Could not start the web server: {e}[/red]\n")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        pass
    console.print("[green]Web UI stopped.[/green]\n")


def _display_host(host: str) -> str:
    """Pick the hostname shown to (and opened for) the user."""
    if host in ("0.0.0.0", "::"):
        return "localhost"
    return host


def _port_in_use(host: str, port: int) -> bool:
    """Pre-check the bind address so port conflicts give an actionable error."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def register(app: typer.Typer) -> None:
    app.command()(web)
