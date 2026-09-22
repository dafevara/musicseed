"""MCP surface smoke tests — tool registration and adapter mapping (no DB/Plex)."""

import asyncio

import pytest
from musicseed_mcp import tools

EXPECTED_TOOLS = {
    "get_status",
    "list_presets",
    "search_tracks",
    "list_playlists",
    "preview_playlist",
    "create_playlist",
    "preview_populate",
    "populate_playlist",
}


def _registered_tools() -> dict[str, object]:
    import musicseed_mcp.server as server

    async def fetch():
        return {t.name: t for t in await server.mcp.list_tools()}

    return asyncio.run(fetch())


def test_server_registers_every_tool():
    assert set(_registered_tools()) == EXPECTED_TOOLS


def test_every_tool_has_a_description():
    for name, tool in _registered_tools().items():
        assert (tool.description or "").strip(), f"{name} has an empty description"


def test_presets_are_the_authoritative_set():
    assert set(tools.list_presets()) == {"balanced", "sonic", "discovery", "popular"}


def test_balanced_preset_is_default_weights():
    from musicseed.recommender.scoring import Weights

    assert tools._weights("balanced") == Weights()


def test_sonic_preset_prefers_sonic_signal():
    assert tools._weights("sonic").sonic > tools._weights("balanced").sonic


def test_unknown_preset_raises_with_choices():
    with pytest.raises(ValueError, match="balanced"):
        tools._weights("bogus")
