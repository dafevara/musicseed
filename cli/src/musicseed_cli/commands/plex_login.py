"""``plex-login`` / ``plex-logout`` — link the Plex account without a token.

The same plex.tv sign-in the web wizard uses, tuned for a terminal: ``--open``
sends the sign-in page to this machine's browser, otherwise MusicSeed prints the
short code to type at ``plex.tv/link`` (the right shape for a remote shell or a
Plex server you can only reach over SSH).

Either way the retrieved token is written to the local MusicSeed config, so
``musicseed-cli`` and the MCP server pick it up without further setup.
"""

import typer
from musicseed.config import get_config_path
from musicseed.exceptions import MusicSeedError

from musicseed_cli.console import console


def plex_login(
    open_browser: bool = typer.Option(
        False,
        "--open",
        "-o",
        help="Open the Plex sign-in page in this machine's browser (default: show a code).",
    ),
    timeout: int = typer.Option(
        600,
        "--timeout",
        help="Seconds to wait for you to approve the sign-in.",
    ),
) -> None:
    """Sign in with your Plex account instead of pasting a Plex token."""
    from musicseed.services import plex_link

    handoff = "forward" if open_browser else "link"
    try:
        start = plex_link.start_plex_link(handoff=handoff)
    except MusicSeedError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    console.print("\n[bold]Sign in with Plex[/bold]\n")
    console.print(f"  1. Open [link={start.link_url}]{start.link_url}[/link]")
    console.print(f"  2. Enter the code [bold cyan]{start.code}[/bold cyan]\n")
    console.print(
        "[dim]Or open this URL while signed in to Plex:[/dim]\n"
        f"[dim]{start.auth_url}[/dim]\n"
    )
    if open_browser:
        import webbrowser

        if not webbrowser.open(start.auth_url):
            console.print(
                "[yellow]Could not open a browser here — use the code above.[/yellow]\n"
            )

    try:
        with console.status("[bold green]Waiting for you to approve the sign-in..."):
            result = plex_link.wait_for_plex_link(start.pin_id, timeout=float(timeout))
    except MusicSeedError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        console.print("\n[yellow]Sign-in cancelled — nothing was saved.[/yellow]")
        raise typer.Exit(1) from None

    if result.expired:
        console.print(
            "[red]That code expired.[/red] Run 'musicseed-cli plex-login' again to get a new one."
        )
        raise typer.Exit(1)
    if not result.linked:
        console.print(
            f"[yellow]Timed out after {timeout}s without approval.[/yellow] "
            "Nothing was saved. Run 'musicseed-cli plex-login' again when ready."
        )
        raise typer.Exit(1)

    name = result.account.title if result.account else "your Plex account"
    console.print(f"[green]✓ Signed in as {name}.[/green]")
    if result.servers:
        console.print(f"  Plex servers on this account: {len(result.servers)}")
        for server in result.servers[:5]:
            console.print(f"  - {server.name} ({server.url})")
    if result.token_saved:
        console.print("  The Plex token was saved to your local MusicSeed config.")
    else:
        console.print("  The stored Plex token was already current.")
    if result.url_saved:
        console.print(f"  Plex server URL set to {result.url_saved}.")
    config_path = get_config_path()
    if config_path is not None:
        console.print(f"\n[dim]Config: {config_path}[/dim]")
    console.print(
        "\n[dim]The web UI and the MCP server read the same config, so no "
        "further setup is needed.[/dim]\n"
    )


def plex_logout() -> None:
    """Forget the stored Plex token (revoke it in Plex to drop the device)."""
    from musicseed.services import plex_link

    if plex_link.unlink_plex():
        console.print("\n[green]✓ Cleared the stored Plex token.[/green]")
        console.print(f"[dim]{plex_link.UNLINK_GUIDANCE}[/dim]\n")
    else:
        console.print("\n[dim]No Plex token was stored.[/dim]\n")


def register(app: typer.Typer) -> None:
    """Attach the ``plex-login`` and ``plex-logout`` commands."""
    app.command("plex-login")(plex_login)
    app.command("plex-logout")(plex_logout)
