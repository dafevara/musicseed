# Local Runtime And Operations

MusicSeed runs locally from source. Infrastructure should remain boring and inspectable. When
something fails, see [`troubleshooting.md`](troubleshooting.md) for concrete checks and recovery
actions.

## Runtime Pieces

- Python 3.12+ packages under `core/src/musicseed` (library), `cli/src/musicseed_cli` (CLI), and
  `api/src/musicseed_api` (REST API), plus `mcp/src/musicseed_mcp` (agent tools).
- A Next.js + React + TypeScript web UI under `web/` (client-rendered SPA) that talks to the API
  over HTTP.
- uv for dependency management and command execution during **development** (per-app lockfiles,
  `uv sync`, `uv run`). Not required for end users: `scripts/install.sh` builds the runtime from
  a plain `python3 -m venv` + `pip`.
- One local SQLite file for MusicSeed's own state (default
  `~/.local/share/musicseed/musicseed.db`, WAL mode) — no database server.
- Plex SQLite database as a read-only import source.
- Plex blobs SQLite database as a read-only source of sonic analysis vectors, imported into
  MusicSeed's local `track_vectors` store (MUS-83); a remote Plex host's files can be fetched
  as consistent snapshots over verified SSH via `plex.db_ssh_target` (see [Remote Plex DB access](#remote-plex-db-access)).
- Optional Plex HTTP API for playlist creation (`core/src/musicseed/clients/plex/`; `plex_api.py` is a compatibility re-export).
- Optional external HTTP APIs: ListenBrainz and Spotify.
- Local logs under `~/.local/share/musicseed/logs/`.

## Database

MusicSeed stores its state in a single SQLite file, configured by `database.path`
(default `~/.local/share/musicseed/musicseed.db`). The engine runs in WAL mode with foreign
keys enabled.

Commands:

```bash
musicseed-cli init-db       # creates the file (and parent dir) and tables
musicseed-cli optimize-db   # search, queue, and tag indexes
musicseed-cli status        # shows the DB path and file size
```

`init-db` creates tables. `optimize-db` creates search, queue, and tag
indexes. `ensure_schema()` applies lightweight additive updates for existing local databases.

For a file-copy backup, stop all MusicSeed processes and ensure the database has closed cleanly.
For a live database or an outstanding WAL, use SQLite's online backup API or `.backup` command;
sequentially copying the database and sidecars does not guarantee a consistent snapshot. See
[backup and recovery](troubleshooting.md#database-backup-and-recovery). PostgreSQL is historical;
the old migration utility is no longer included in this checkout.

## Configuration

Config lookup order:

1. `~/.config/musicseed/config.yaml`
2. `~/.musicseed.yaml`
3. `config.yaml`

The CLI can override lookup with `musicseed-cli --config /path/to/config.yaml COMMAND`.
Without a matching file, core uses model defaults. Environment variables and `~` are expanded
in YAML values. Saving settings writes back to the resolved file, or to the canonical
`~/.config/musicseed/config.yaml` if no file was found. Keep credentials out of tracked files.

Plex credentials come from a Plex account sign-in (the plex.tv PIN flow), not from a token the
user has to find: the wizard and Settings offer **Sign in with Plex**, which writes the returned
access token into `config.yaml`. `musicseed-cli plex-login` does the same from a terminal
(`--open` sends the browser to Plex, otherwise MusicSeed prints a code to enter at
`plex.tv/link`), and `plex-logout` clears it. A hidden **Advanced** field still accepts a manual
token for installs that cannot reach plex.tv.

None of that is required when Plex runs on the same machine: discovery auto-detects the token by
reading `PlexOnlineToken` from Plex's `Preferences.xml`, falling back to `.LocalAdminToken`
(localhost-only). It probes the usual macOS path (`~/Library/Application Support/Plex Media
Server/`) and Linux locations (`/var/lib/plexmediaserver/...`, snap,
`~/.local/share/plexmediaserver/...`). Saving setup or settings persists the detected token into
`config.yaml`, which is written owner-only (`0600`) because it holds credentials.

## Remote Plex DB Access

By default MusicSeed reads Plex's two SQLite files (library metadata + blobs/sonic vectors)
from the local filesystem — the blobs file only at import time, when its vectors are copied into
the local `track_vectors` store. For a remote Plex server (e.g. a NAS on the LAN), set
`plex.db_ssh_target` to an scp-style target for the directory that holds them:

```yaml
plex:
  db_ssh_target: "admin@nas.local:/volume1/Plex/.../Databases"
  db_ssh_password: "your-password"   # optional — omit to use ~/.ssh keys
  db_ssh_port: 22                    # optional
```

The target is forgiving about real pastes: the path to the database file itself is accepted
(its folder is used), `~` is expanded on the remote host, quotes around the target or the path
are stripped, and spaces do not need escaping:

```yaml
  # all four are the same source
  db_ssh_target: "admin@nas.local:/volume1/Plex/Plug-in Support/Databases"
  db_ssh_target: "admin@nas.local:~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
  db_ssh_target: "admin@nas.local:\"/volume1/Plex/Plug-in Support/Databases\""
  db_ssh_target: "admin@nas.local:/volume1/Plex/Plug-in\ Support/Databases/"
```

The remote host needs **SSH command execution, `python3` with the standard-library
`sqlite3` module, read access to Plex's databases, and enough temporary space for both
backups**. MusicSeed runs a small bundled helper over SSH: SQLite's online backup API reads
committed pages (including WAL contents) into independent standalone database files, then
streams those files back. No helper installation, HTTP server, Plex shutdown, or copying of
live `-wal`/`-shm` files is needed. Backup does not rebuild Plex's custom indexes/collations.
Each database has a consistent snapshot; the two databases are backed up sequentially, not
in a cross-database transaction. Missing blobs are optional; an unreadable or invalid supplied
backup fails the refresh. Local-file mode is unchanged: use local Plex files or consistent
backups, not arbitrary copies of a running remote server's databases.

**Host identity is verified.** First verify the server's fingerprint through a trusted channel,
then connect once as the same local OS user that runs MusicSeed:

```bash
ssh -p 22 admin@nas.local
```

This establishes trust in `~/.ssh/known_hosts` (non-default ports use their own known-hosts
entry). Unknown or changed host keys fail closed. Never blindly accept a changed fingerprint
or use unverified `ssh-keyscan` output as proof of identity. When `db_ssh_password` is set,
MusicSeed uses that password; otherwise it uses standard key files and the SSH agent. Paramiko
does not interpret `~/.ssh/config` aliases: supply the actual host, user and port.

**Non-interactive authentication matters.** paramiko never prompts. A key that only exists in
your terminal's agent is invisible to a MusicSeed process that lacks `SSH_AUTH_SOCK`, which
typically looks like "`scp` works, but the web UI cannot connect". Load the key with `ssh-add`
and make sure whatever starts MusicSeed (shell, `systemd` unit, `launchd` agent, container)
inherits `SSH_AUTH_SOCK` — or set `db_ssh_password`. MusicSeed reports authentication failure
with that guidance instead of a generic connection error.

**Remote failures report a reason, not a traceback.** The bundled helper returns one short
code (`not_found`, `not_a_directory`, `database_not_found`, `unreadable`, `timeout`, `other`)
which becomes an actionable message; host-local paths and tracebacks are never shown in the UI.

**The long wait is visible.** A remote refresh reports progress in two phases, both as a
percentage:

- `preparing Plex snapshot` — the host is running SQLite's online backup. Nothing is transferred
  during this window, and it is the slow part for a large library (minutes on a busy server).
- `downloading Plex database` / `downloading Plex sonic-vector database` — the transfer of each
  file back to this machine.

The web job view shows a bar per phase; `musicseed-cli import` prints the same phases at 25%
steps. Each database gets a five-minute backup budget on the host, after which the helper reports
`timeout`: retry when Plex is idle. A phase that never advances at all means the remote work is
not running (see `logs/latest.log` for the SSH probe result), while a phase that crawls is simply
a large library over a slow link — the bar is real progress, not an estimate.

Each refresh downloads into a private generation under
`~/.cache/musicseed/plex-dbs/snapshots-v1/` (or `$XDG_CACHE_HOME/musicseed/plex-dbs/`).
The cache key includes target and port. MusicSeed validates bounded headers, file/page sizes,
and schema readability, plus SQLite `quick_check` where supported, then atomically publishes
the complete generation. Plex-specific collations can prevent stock SQLite's `quick_check`;
in that case validation is structural only, not a claim of full index integrity. Failed
backups/transfers leave the previous published generation untouched; absent optional blobs
never inherit an older copy. Legacy live-file caches are ignored and require one new import.
`import` and `import-plex-sonic` each refresh; status reuses the published snapshot without
SSH access. Recommendations use MusicSeed's own local database.

Old published generations are retained so active readers keep stable paths. They consume disk
space; **only while MusicSeed and all CLI imports are stopped**, you may remove this source's
cache directory to reclaim space (the next import recreates it). Do not remove MusicSeed's
own database. Remote temporary backups are cleaned when the helper exits normally; abrupt
host/process failure can leave `musicseed-snapshot-*` temporary directories for host-side
cleanup. A backup that cannot finish within five minutes fails; retry when Plex is less busy.
Transfer inactivity times out after six minutes.

If refresh fails, check host trust, Python/SQLite availability, database permissions, remote
and local free space, and Plex activity. Fix the cause and rerun the import; do not repair a
bad cache by copying live sidecars. SSH credentials stay in `config.yaml` like the Plex token
and are not included in the snapshot stream.

## Web UI, First-Run Wizard, And Settings

The web UI is the default onboarding path. Users run `./scripts/install.sh` then `musicseed`,
which serves the API and the static UI on `127.0.0.1:8789`. `./scripts/dev.sh` is contributor
hot reload (API + `next dev` on port 3000 + MCP on port 8790).

- **First-run wizard** (`/setup`): detects the Plex server (local-network discovery plus a
  manual URL), initializes the database, and optionally runs import and enrichment. Non-setup
  pages (dashboard, recommend, playlists) redirect back here while the library is missing or
  empty.
- **Settings** (`/settings`): a persistent view for the Plex account sign-in (plus a manual token
  under **Advanced**), Plex URL/library, the MusicSeed database path, Spotify credentials, and the
  local sonic-vector import action. Saving persists config without starting any import,
  enrichment, or database initialization.
- **Plex discovery**: local-network discovery is passive and read-only — GDM multicast on
  `239.0.0.250:32414` with an SSDP fallback on `239.255.255.250:1900`
  (`urn:plex-com:service:pms:1`), stdlib-only. Multicast never crosses routers, so servers on
  other subnets are found via `plex.tv/api/resources` once a Plex account is linked. Each
  advertised address is then probed (`/identity`) and reported as `reachable`, because a server's
  own LAN addresses are often unreachable from another machine — the picker sorts answerers first
  and marks the address in use.

Relevant API routes: `GET /discovery`, `GET /discovery/plex-servers`,
`POST /discovery/check`, `POST /discovery/config` (save-only), `POST /discovery/init-db`,
`POST /auth/plex/pin`, `GET /auth/plex/pin/{pin_id}`, `GET /auth/plex/account`,
`POST /auth/plex/unlink`.
These paths are relative to the JSON base URL: prepend `/api` for the normal `musicseed`
server. See [HTTP API modes](../api-reference/http-api.md#server-modes-and-openapi).

### Import state and recovery

- Import/enrichment services and API background jobs share **one writer per MusicSeed database**.
  A SQLite transaction checks and claims the writer atomically. Pending jobs and cancellation
  requests still reserve it; completion is published after the worker target returns.
- Each job captures a deep copy of its runtime configuration. Work, progress callbacks, and job
  state writes use that context even if the process default later changes. Settings rejects
  changes while jobs are active; it saves a copy before replacing the default context.
- Source/library-specific `import_state` records store the input snapshot identity, expected
  counts, last committed phase, and completion time. Deleting job history does not delete these
  records. Old successful job rows and equal aggregate counts alone are **not verified coverage**;
  rerun an incremental import once to establish provenance on an older installation.
- An initial partial/failed import remains incomplete. Later Plex count drift is advisory once
  that source has completed an import. A different source/library does not inherit its completion.
  No automatic deletion or catalog replacement occurs when changing sources; use a separate
  MusicSeed database if you want an independent library.
- Vector upserts commit in batches of 500 by default. Progress callbacks and cancellation checks
  run outside write transactions; canceled/failed runs retain committed batches and can be rerun.
  Snapshot transfer and source decoding still finish before cancellation can be checked again.
- Each committed vector batch increments `runtime_state.sonic_generation`. API and CLI contexts
  check it before reusing cached vectors; a restart is not required after another process imports.
  Direct SQL edits to vector rows must also update this generation or explicitly reset caches.
- Discovery does not initialize or migrate MusicSeed databases. It reports separate capabilities:
  `can_import` (readable configured source and usable destination), `can_recommend` (local tracks),
  and `can_write_playlists` (authorized Plex connection). An unreachable Plex HTTP API need not
  prevent local import/recommendation. A fallback path suggestion must be saved before import.
  The setup wizard refreshes both discovery and library status when a job finishes.

### Ports

`musicseed` listens on `127.0.0.1:8789` (JSON at `/api`, UI at `/`). `musicseed --no-ui`
serves unprefixed JSON. Contributor `dev.sh` starts that unprefixed API, Next.js on
`127.0.0.1:3000`, and MCP streamable HTTP on `127.0.0.1:8790`. It reads `API_PORT`, `WEB_PORT`,
`API_URL`, and `MCP_PORT`; when changing `API_PORT`, also set `API_URL` for the Next.js proxy.
The script binds services to loopback. See the [MCP reference](../mcp-reference.md) for stdio
and standalone transports.

### Offline behavior

The web UI and API are fully local and need no internet once the app is running. Internet access
is required only for enrichment providers (ListenBrainz, and optional Spotify) and for the
cross-subnet Plex lookup through `plex.tv`; without it, discovery falls back to local-network
multicast and a manual URL, and enrichment is simply skipped for tracks it can't reach.

## Logging

CLI, API product server, and MCP configure file logging through
`core/src/musicseed/logging_config.py`. `MUSICSEED_LOG_LEVEL` takes precedence over configured
or command-line levels. The API also attaches uvicorn to these handlers. MCP logs to stderr
so stdout remains available for JSON-RPC. `scripts/dev.sh` defaults to DEBUG and also captures
MCP process output in repo-local `logs/mcp.log` (override with `MCP_LOG`).

- Timestamped run logs: `~/.local/share/musicseed/logs/musicseed_YYYYMMDD_HHMMSS.log`
- Latest run: `~/.local/share/musicseed/logs/latest.log`

When changing pipelines, log enough detail to diagnose failed batches without flooding console
output. Console output should summarize progress and outcome.

## Safe Development Commands

These are cheap and should be used before heavier checks:

```bash
python3 -m compileall -q core/src/musicseed cli/src/musicseed_cli api/src/musicseed_api mcp/src/musicseed_mcp
uv run --project core ruff check core/src
uv run --project cli musicseed-cli --help
.venv-docs/bin/mkdocs build --strict
```

From the repository root, use bounded enrichment and read-only previews during development
(the examples below require configured local data; replace `123` with a real track ID):

```bash
uv run --project cli musicseed-cli enrich --source listenbrainz --limit 100 --batch-size 50 --resume
uv run --project cli musicseed-cli sonic-probe
uv run --project cli musicseed-cli recommend --seed-id 123 --limit 20 --explain
```

`recommend` is already read-only; there is no `--dry-run` option. `import` and
`import-plex-sonic` have no limit/dry-run flags and should only be run against real data with
explicit intent. Use disposable fixtures for import exploration.

## Slow Or Risky Operations

Ask before running:

- Full Plex import on the user's real library.
- Full ListenBrainz or Spotify enrichment.
- Triggering Plex's MusicAnalysis Butler task (`sonic-refresh`, `sonic-probe --trigger-butler`).
- Any operation that writes or rewrites Plex playlists.
- Deleting or replacing the MusicSeed SQLite database file.

## External APIs

ListenBrainz enrichment uses recording MBIDs and should be the default enrichment path when
possible. It requires a free ListenBrainz user token (`listenbrainz.token`), which raises rate
limits over anonymous access. Spotify requires credentials and text matching, so treat it as a
fallback.

HTTP clients should:

- Respect rate limits and retries.
- Use bounded concurrency.
- Commit progress in batches.
- Mark attempted tracks so interrupted jobs can resume.

## Harness Sensors

For this small project, useful sensors are intentionally simple:

- Computational sensors: compileall, Ruff, CLI help, small dry runs, limited DB commands.
- Runtime sensors: `logs/latest.log`, status coverage tables, explainable recommendation output.
- Human sensors: review playlists manually before writing to Plex.

Avoid adding CI, custom linters, or observability stacks until repeated failures justify them.
