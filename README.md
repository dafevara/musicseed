# MusicSeed

MusicSeed helps you find something else to play from the music you already own.

Start with a few songs, explore recommendations from your Plex collection, and save the tracks
you choose as a playlist. Use the browser interface, work from the terminal, or connect your
agent and ask it to put a mix together. Listen through your usual Plex music client.

It's a personal, open-source DIY project for collectors who enjoy tinkering. The recommendation
engine and library database run locally. The backlog includes actually listening to the music.

[Website and screenshots](https://musicseed.org/) ·
[Setup guide](https://musicseed.org/quick-start/) ·
[Documentation](https://docs.musicseed.org/) ·
[Releases](https://github.com/dafevara/musicseed/releases)

## Choose how you make a playlist

| Interface | What you can do |
|---|---|
| **Web UI** | Set up your library, choose seed songs, adjust recommendations, review tracks, and create or extend Plex playlists. |
| **CLI** | Import and enrich your library, inspect recommendation scores, and preview and save playlists from the terminal. |
| **Agent via MCP** | Ask your connected agent to search the library, suggest a mix, or find additions to an existing playlist, then save the selection you approve. |

All three use the same local library and recommendation engine. Playback happens in Plexamp
or another Plex music client. MusicSeed is built for one owner and their collection, with Plex
running on the same computer, another server, or a NAS.

## Make playlists with your agent

Once your library is prepared, connect MusicSeed's MCP server to your agent or harness. Try:

> Build a 20-track playlist around these three songs. Show me the recommendations before saving.

> Find 10 complementary tracks for my Evening Mix playlist. Let me review them before adding.

The agent searches for your seed tracks, previews recommendations, and saves the IDs you approve.
It can create a playlist or append to an existing one. Write tools validate the selected tracks
and handle exact retries without duplicating the playlist or re-adding tracks.

**Prepare the library first:** sign in to Plex, initialize MusicSeed, and import your library
through the [setup flow](#connect-and-import-your-library) or CLI. MCP shares that configuration;
it does not perform sign-in or library import. You can close the web app after setup when using
the default stdio connection.

**MCP is a separate setup:** `scripts/install.sh` installs the web app and CLI, but does not
install `musicseed-mcp`. One launch option uses `uv` to run the MCP project from your checkout:

```json
{
  "mcpServers": {
    "musicseed": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/musicseed/mcp", "musicseed-mcp"]
    }
  }
}
```

Install `uv` for this option, replace the project path, and use your host's MCP configuration
format. The host must be able to find `uv`; use its absolute executable path if needed.
Compatibility depends on the host's MCP support and configuration. Agent/model hosting and
any data sent to a model depend on your chosen agent.

Stdio is the default: the host starts MusicSeed on demand, with no listening port or web app
required. Streamable HTTP and SSE are also available for hosts that connect to a URL.
See the [MCP setup guide](mcp/README.md), [tool reference](docs/mcp-reference.md), and optional
[agent skill](mcp/SKILL.md) for configuration and the preview → approval → save workflow.

## Requirements

For a single-image container installation, see [Docker setup](docs/infra/docker.md).
It includes the web UI, API, CLI, and MCP; only Docker is needed on the host. The following
requirements apply to installation from source.

- **macOS or Linux.** Windows is untested.
- **Python 3.12+** with `venv`. The installer bootstraps `pip` if needed.
- **Node.js and npm** for the standard installer to build the web UI. Runtime is Python only;
  the CLI and stdio MCP server operate without the web UI or a running HTTP API.
- **Plex Media Server with a music library** you own or administer, plus access to its library
  database. Use local files, an SSH snapshot from a server/NAS, or a copied database backup.
- **SQLite support.** MusicSeed stores its library in one local SQLite database; no database
  server is required.

**Optional:** import Plex's existing sonic analysis to enable sound similarity, and enrich
popularity with a ListenBrainz user token or Spotify API credentials. Recommendations work
without enrichment or sonic vectors. These signals add information to the recommendations;
they are not prerequisites for getting started.

## Install

### Release archive

Download `musicseed-<version>.tar.gz` and its `.sha256` checksum from
[Releases](https://github.com/dafevara/musicseed/releases), unpack it, then:

```bash
cd musicseed-*
./scripts/install.sh
musicseed
```

### Git checkout

```bash
git clone https://github.com/dafevara/musicseed.git
cd musicseed
./scripts/install.sh
musicseed
```

Open `http://127.0.0.1:8789`. The installer creates `.venv/`, installs core + API + CLI using
the pinned dependencies in `constraints.txt`, and builds the static web UI with `npm ci` and
`npm run build`. It links both `musicseed` and `musicseed-cli` into `~/.local/bin`; add that
directory to your PATH if prompted. Keep the checkout or unpacked release in place: the
installation uses editable packages and links to that directory.

The standard install does not require `uv`. The agent launch example above uses it separately.

## Connect and import your library

The first-run wizard guides you through:

1. **Sign in with Plex, then choose your server.** Account linking avoids manually copying a
   token. Local discovery and your linked account help find servers; reachable addresses are
   listed first. A manual URL and token remain available under Advanced.
2. **Review the music library and database paths.** Confirm the detected values, or configure
   access to Plex on another machine. Initialize MusicSeed's own database.
3. **Import your library.** MusicSeed copies metadata and play history into its local store.
   The dashboard shows import progress and library coverage.
4. **Add optional signals.** Enrich popularity with ListenBrainz or Spotify, and import existing
   Plex sonic vectors from **Library coverage** when available. Missing sonic vectors do not
   prevent recommendations.

Open **Help** in the navigation (`/quick-start`) for instructions on local Plex installations,
remote servers/NAS over SSH, and manually copied backups. Help is available before setup is
complete. The [public setup guide](https://musicseed.org/quick-start/) covers these paths too.

**Settings** holds Plex sign-in, the server URL and library, database paths, the ListenBrainz
token, and Spotify credentials. Saving settings does not start an import or initialize a database.
For headless sign-in, use `musicseed-cli plex-login`; add `--open` to launch the browser.

## Shape your recommendations

MusicSeed scores tracks already in your imported library using six signals: sonic similarity,
popularity proximity, style, genre, era, and novelty from play history. Popularity compares a
track with the seeds' popularity; it does not simply favor the biggest hits.

- **Average** combines the seed songs into one profile and scores the library against it.
- **Frequency** scores against individual seeds, combines the recommendations, and records
  which seeds contributed. It does more work for larger seed sets.
- **Presets and controls** let you change the emphasis: balanced, sonic, discovery, or popular.
  The web UI and CLI also support custom signal weights. Year filters and artist limits help
  shape the selection; MCP exposes named presets and filters.
- **Explanations** show the score components and missing signal data through web tooltips and
  the CLI's `--explain` option.

Create a new playlist from seed songs, or use an existing playlist to find complementary tracks.
The web, CLI, and MCP playlist flows preview the selection before writing it to Plex.

When **extending an existing playlist in the web UI**, both average and frequency previews run
in the background with elapsed time and scan progress. You can stop or retry a calculation,
and refreshing the same browser tab reconnects to its running preview. Results appear when the
calculation finishes; saving them remains a separate action.

Popularity enrichment queries ListenBrainz using MusicBrainz recording IDs, with Spotify as a
credentialed fallback.
Sonic similarity uses Plex's existing analysis vectors imported from its blobs database into
MusicSeed's local store. MusicSeed does not generate audio embeddings. See
[how recommendations work](docs/resolvers/recommendation-resolvers.md) for scoring, methods,
and signal availability.

## Work from the terminal

`musicseed-cli` works directly with the library, without a running web app. After installation
and library setup, for example:

```bash
musicseed-cli status
musicseed-cli recommend --seed "Artist - Title" --limit 20 --explain
musicseed-cli playlist --name "My Mix" --seed "Artist - Title"
musicseed-cli populate --playlist "My Mix" --dry-run
```

Replace `Artist - Title` with a track in your library. Playlist creation previews the tracks
and asks for confirmation; `populate --dry-run` only previews additions. Run `populate` without
`--dry-run` to review and confirm a write.

The CLI also supports database initialization, import, sonic-vector import, and optional
enrichment. See the [CLI guide](cli/README.md) and [command reference](docs/cli-reference.md).

## Operation and troubleshooting

`musicseed` listens on `127.0.0.1:8789` by default. `musicseed --open` opens the browser;
`musicseed --no-ui` serves JSON only. Use `musicseed --lan` to make the UI reachable on a
trusted home network.

The API has host, origin, and CSRF protections, and MCP HTTP transports have host/origin
protections. These do not provide user authentication: clients that can reach the service
can exercise its permissions. Keep LAN access on a network you trust. Public Plex connections
over plain HTTP are refused by default; local, home-LAN, and VPN connections remain supported.

Configuration, database, and log files are created with owner-only permissions. Configuration
is saved atomically. See [security details](SECURITY.md) and [example configuration](config.example.yaml)
for connection settings, allowed hostnames, and configurable limits on expensive work.

MusicSeed's database defaults to `~/.local/share/musicseed/musicseed.db`; logs are under
`~/.local/share/musicseed/logs/`, including `latest.log`. To back up the database by copying it,
first cleanly shut down every MusicSeed process, including agent-launched MCP processes. For a
live database or a remaining WAL after interrupted shutdown, use SQLite's online backup API or
`.backup` command. See [backup and recovery](docs/infra/troubleshooting.md#database-backup-and-recovery).

For connection failures, SSH imports, enrichment, and job recovery, see
[troubleshooting](docs/infra/troubleshooting.md). Keep real configuration, credentials, database
copies, and logs out of commits and public issue attachments.

## Development

MusicSeed is a monorepo of apps sharing one core library. Each Python app has its own
`pyproject.toml`, `uv.lock`, and development virtualenv; the web app uses npm.

| Directory | Responsibility |
|---|---|
| [`core/`](core/README.md) | Library import, enrichment, sonic vectors, recommendations, database, and shared services. |
| [`api/`](api/AGENTS.md) | FastAPI endpoints and the `musicseed` command, which serves the API and static web UI. |
| [`web/`](web/AGENTS.md) | Next.js/React UI; `npm run build` exports static files to `web/out/`. |
| [`cli/`](cli/README.md) | Typer CLI, calling core services directly. |
| [`mcp/`](mcp/README.md) | Agent tools over core services; stdio by default, with optional Streamable HTTP/SSE. |

`./scripts/dev.sh` starts the API, Next.js development server, and MCP HTTP server for contributor
hot reload. Python development environments use `uv`; for example,
`cd cli && uv sync && uv run musicseed-cli --help`.

For contributors and coding agents, start with [AGENTS.md](AGENTS.md) and the relevant app guide.
Further reading: [product overview](docs/product/overview.md),
[local runtime](docs/infra/local-runtime.md), and
[dependency architecture](docs/musicseed-dependency-architecture.html).

## License

MusicSeed is [MIT licensed](LICENSE). Report vulnerabilities through the process in
[SECURITY.md](SECURITY.md).
