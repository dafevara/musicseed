"""MusicSeed MCP server — agentic playlist creation and population.

A thin stdio MCP surface over ``musicseed-core``'s synchronous ``services/``
layer. Every tool offloads its sync service call to a worker thread so the
MCP event loop is never blocked, and every write tool uses only
previously-approved local track IDs (core validates the full selection before
any Plex write).

Launched on demand by an MCP host (Claude Desktop, Codex, opencode, pi, ...):
    musicseed-mcp          # stdio transport
"""

from __future__ import annotations

from anyio import to_thread
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from musicseed_mcp import tools

_WORKFLOW = (
    "Resolve seed tracks with search_tracks, preview with preview_playlist, "
    "then call create_playlist with the approved recommendation IDs. For an "
    "existing playlist, use preview_populate then populate_playlist. Never pass "
    "IDs that were not shown in a preview to a write tool; writes are "
    "idempotent and report both added_count and already_present_count. "
    "If a tool reports that Plex is not linked, stop and tell the user to "
    "sign in through the MusicSeed web interface or run "
    "'musicseed-cli plex-login' — this server never signs in interactively "
    "and cannot store credentials itself."
)

mcp = MCPServer("musicseed", instructions=_WORKFLOW)


@mcp.tool()
async def get_status() -> dict:
    """Return MusicSeed library status and enrichment coverage."""
    return await to_thread.run_sync(tools.get_status)


@mcp.tool()
async def list_presets() -> dict[str, dict[str, float]]:
    """List the named recommendation weight presets (balanced, sonic, discovery, popular)."""
    return await to_thread.run_sync(tools.list_presets)


@mcp.tool()
async def search_tracks(query: str, limit: int = 10) -> list[dict]:
    """Search the local library by track title or artist (substring, min 2 chars).

    Use this to resolve free-text seed names into local track IDs before
    calling preview_playlist.
    """
    return await to_thread.run_sync(tools.search_tracks, query, limit)


@mcp.tool()
async def list_playlists() -> list[dict]:
    """List existing Plex audio playlists with rating_key and track count."""
    return await to_thread.run_sync(tools.list_playlists)


@mcp.tool()
async def preview_playlist(
    seed_ids: list[int],
    seed_texts: list[str] | None = None,
    limit: int = 50,
    preset: str = "balanced",
    method: str = "average",
    per_seed_limit: int = 30,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> dict:
    """Preview recommendations for a new playlist without writing to Plex.

    Provide resolved seed track IDs (from search_tracks) or free-text
    "Artist - Title" seeds. Returns seed_tracks plus scored recommendations
    with per-signal breakdowns; approve a subset of the recommendation IDs and
    pass them to create_playlist.
    """
    return await to_thread.run_sync(
        tools.preview_playlist,
        seed_ids,
        seed_texts,
        limit,
        preset,
        method,
        per_seed_limit,
        year_min,
        year_max,
        max_tracks_per_artist,
        min_score,
    )


@mcp.tool()
async def create_playlist(name: str, seed_ids: list[int], track_ids: list[int]) -> dict:
    """Create a Plex playlist from an approved ordered selection (seeds first).

    seed_ids are the resolved seed tracks (included first); track_ids are the
    approved recommendation IDs from preview_playlist. Writes to Plex and is
    idempotent: retrying with the same name and identical contents returns the
    existing playlist rather than creating a duplicate.
    """
    return await to_thread.run_sync(tools.create_playlist, name, seed_ids, track_ids)


@mcp.tool()
async def preview_populate(
    playlist_id: str,
    limit: int = 10,
    preset: str = "balanced",
    method: str = "average",
    per_seed_limit: int = 30,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> dict:
    """Preview complementary tracks for an existing Plex playlist without writing.

    playlist_id is the playlist's rating_key (from list_playlists). Approve a
    subset of the returned recommendation IDs and pass them to populate_playlist.
    """
    return await to_thread.run_sync(
        tools.preview_populate,
        playlist_id,
        limit,
        preset,
        method,
        per_seed_limit,
        year_min,
        year_max,
        max_tracks_per_artist,
        min_score,
    )


@mcp.tool()
async def populate_playlist(playlist_id: str, track_ids: list[int]) -> dict:
    """Append approved local track IDs to an existing Plex playlist.

    playlist_id is the playlist's rating_key (from list_playlists). Writes to
    Plex and is idempotent: already-present tracks are not re-added and are
    reported in already_present_count.
    """
    return await to_thread.run_sync(tools.populate_playlist, playlist_id, track_ids)


def main() -> None:
    """Run the MCP server (stdio by default, or a listening HTTP transport).

    stdio is the production mode: an MCP host spawns ``musicseed-mcp`` and
    talks JSON-RPC over stdin/stdout. ``--transport sse`` or
    ``--transport streamable-http`` start a listening endpoint (for
    ``scripts/dev.sh`` or hosts that connect over a URL). Loopback binds get
    the SDK's built-in DNS-rebinding protection; a non-loopback (LAN) bind
    requires ``security.allowed_hosts`` entries and applies the same
    protection to the names the operator configured.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="musicseed-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="stdio (default, spawned by an MCP host) or a listening HTTP transport",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host for HTTP transports")
    parser.add_argument("--port", type=int, default=8790, help="bind port for HTTP transports")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(
            transport=args.transport,
            host=args.host,
            port=args.port,
            transport_security=_transport_security(args.host),
        )


def _transport_security(host: str) -> TransportSecuritySettings | None:
    """DNS-rebinding protection for a listening HTTP transport.

    Loopback binds rely on the SDK's built-in loopback-only protection (which
    auto-enables for ``127.0.0.1``/``localhost``/``::1``). A non-loopback (LAN)
    bind instead enforces the operator's ``security.allowed_hosts`` entries
    plus the concrete bind host, so only named hosts/origins can reach the
    server.
    """
    if host in ("127.0.0.1", "localhost", "::1"):
        return None
    from musicseed.config import get_config

    names = list(get_config().security.allowed_hosts)
    if host not in ("0.0.0.0", "::") and host not in names:
        names.append(host)
    hosts = [f"{name}:*" for name in names]
    origins = [f"http://{name}:*" for name in names]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


if __name__ == "__main__":
    main()
