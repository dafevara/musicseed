# MCP Tools and Transports

`musicseed-mcp` exposes eight typed tools over core services. It does not depend on the FastAPI
app. Each async tool offloads its synchronous adapter to `anyio.to_thread.run_sync` and returns
JSON-safe data. Core errors propagate as tool errors.

## Run

From the repository root (after `uv sync --project mcp`):

```bash
uv run --project mcp musicseed-mcp
uv run --project mcp musicseed-mcp --transport streamable-http --host 127.0.0.1 --port 8790
```

The default `stdio` transport is launched by an MCP host; it uses stdin/stdout for JSON-RPC.
`sse` and `streamable-http` are optional listening transports, defaulting to `127.0.0.1:8790`.
`scripts/dev.sh` starts the streamable HTTP server alongside the API and Next.js.

The server uses core's YAML config lookup and the same local SQLite database as the CLI/API.
It does not expose setup, import, enrichment, or sonic-analysis mutation tools; complete setup
through the web UI or CLI. Logs go to MusicSeed's standard log directory and stderr; stdout
is reserved for the stdio protocol. `MUSICSEED_LOG_LEVEL` controls verbosity.

## Preview, approve, apply

1. `search_tracks` resolves local seeds; `list_presets` returns `balanced`, `sonic`, `discovery`,
   and `popular` weight maps.
2. `preview_playlist` returns `seed_tracks` and `recommendations` (IDs at `track.id`). For
   text-only seeds, pass `seed_ids=[]` plus `seed_texts=["Artist - Title"]`.
3. Show the preview and obtain approval for the selection.
4. `create_playlist` receives the resolved `seed_ids` and approved recommendation `track_ids`.
   Seeds are written first, preserving the selection order.

For an existing playlist, use `list_playlists` → `preview_populate` → approval →
`populate_playlist`. `playlist_id` is Plex's string `rating_key`; track IDs are local MusicSeed
integers. Previewing an existing playlist reads Plex over HTTP; previewing local seed tracks
uses the local store.

Both previews accept presets, `average`/`frequency`, limits, year filters, artist caps, and a
minimum score. Tools expose named presets rather than six individual weight parameters.
Write tools take IDs only and never rescore. Caller approval is a workflow requirement; the
server does not issue or check a stored preview token. Core validates the entire local selection
and Plex mappings before writing, rejecting stale selections and deduplicating in first-seen order.

Creation retries with the same title and identical ordered contents return the existing playlist;
a title collision with different contents fails. The result contains `playlist` and `tracks`.
Population reconciles against current Plex contents and returns `added_count` and
`already_present_count`. These count fields belong to populate, not create.

## Tool signatures and descriptions

The following signatures and descriptions come directly from the registered tool wrappers.

::: musicseed_mcp.server
    options:
      members:
        - get_status
        - list_presets
        - search_tracks
        - list_playlists
        - preview_playlist
        - create_playlist
        - preview_populate
        - populate_playlist
