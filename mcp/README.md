# musicseed-mcp

MCP server exposing MusicSeed playlist management (create and populate) as
typed agent tools. A thin stdio surface over `musicseed-core`'s `services/`
layer — no web server, no listening port, no HTTP. An MCP host (Claude
Desktop, Codex, opencode, pi, …) launches it on demand and it talks to the
same SQLite database and Plex server the CLI uses.

## Tools

| Tool | Writes to Plex? | Purpose |
|---|---|---|
| `get_status` | no | Library status and enrichment coverage |
| `list_presets` | no | Named recommendation weight presets |
| `search_tracks` | no | Resolve free-text seed names to local track IDs |
| `list_playlists` | no | Existing Plex playlists (name, `rating_key`, count) |
| `preview_playlist` | no | Scored recommendations for a new playlist |
| `create_playlist` | **yes** | Create a playlist from an approved selection |
| `preview_populate` | no | Scored complementary tracks for an existing playlist |
| `populate_playlist` | **yes** | Append an approved selection to an existing playlist |

## Workflow (the agent follows this)

1. `search_tracks` to resolve ambiguous free-text seeds into IDs.
2. `preview_playlist` (new) or `preview_populate` (existing) — read-only.
3. Show the preview; approve a subset.
4. `create_playlist` / `populate_playlist` with **only the approved IDs**.

Writes never recompute recommendations and never silently write a subset:
missing or stale IDs reject the whole write. Writes are idempotent — retrying
after a lost response reconciles against Plex's current playlist contents and
reports `added_count` and `already_present_count` separately.

A host-agnostic [SKILL.md](SKILL.md) teaches the full workflow (seed
resolution, preview → approve → write, preset use, failure handling) to agents
that support skills. The MCP server's `instructions` and tool descriptions
carry the same guidance for hosts that do not.

## Configure a host

The server reads the same config as the CLI (`~/.config/musicseed/config.yaml`
or `~/.musicseed.yaml`). Register it as a stdio server, for example:

```json
{
  "mcpServers": {
    "musicseed": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/musicseed/mcp", "musicseed-mcp"]
    }
  }
}
```

For a globally installed environment, `"command": "musicseed-mcp"` with no
args works after `pip install`/`uv tool install`.

stdio is the default and preferred transport. For a host that connects over a
URL instead of spawning a subprocess, run a listening transport:

```bash
musicseed-mcp --transport streamable-http --host 127.0.0.1 --port 8790
# or: --transport sse
```

`scripts/dev.sh` at the repo root starts the API (8789), web UI (3000), and the
MCP server (8790, streamable-http) together; override with `MCP_PORT`.

## Develop / verify

```bash
cd mcp
uv sync
uv run ruff check src tests
uv run pytest tests -q            # offline; asserts tool registration and preset mapping
uv run musicseed-mcp              # starts the stdio server (feed it JSON-RPC to drive tools)
uv run musicseed-mcp --transport streamable-http --port 8790   # listening endpoint for HTTP hosts
```
