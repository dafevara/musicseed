# Local Runtime And Operations

MusicSeed runs locally from source. Infrastructure should remain boring and inspectable. When
something fails, see [`troubleshooting.md`](troubleshooting.md) for concrete checks and recovery
actions.

## Runtime Pieces

- Python 3.12+ packages under `core/src/musicseed` (library), `cli/src/musicseed_cli` (CLI), and
  `api/src/musicseed_api` (REST API).
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
- Optional Plex HTTP API for playlist creation (`core/src/musicseed/clients/plex_api.py`).
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

Backup and restore are file operations: copy `musicseed.db` (plus `-wal`/`-shm` if copying
while in use). A one-shot migration from the retired Postgres setup lives at
`scripts/migrate_pg_to_sqlite.py` (`uv run scripts/migrate_pg_to_sqlite.py` from the repo
root).

## Configuration

Config lookup order:

1. `~/.config/musicseed/config.yaml`
2. `~/.musicseed.yaml`
3. `config.yaml`

Environment variables and `~` are expanded. Keep credentials out of repo-local tracked files.

The Plex token is auto-detected when possible: discovery reads `PlexOnlineToken` from Plex's
`Preferences.xml`, falling back to `.LocalAdminToken` (localhost-only). It probes the usual
macOS path (`~/Library/Application Support/Plex Media Server/`) and Linux locations
(`/var/lib/plexmediaserver/...`, snap, `~/.local/share/plexmediaserver/...`). Saving setup or
settings persists the detected token into `config.yaml`; when none is found the UI shows how
to retrieve one from app.plex.tv.

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
hot reload (API + `next dev` on port 3000).

- **First-run wizard** (`/setup`): detects the Plex server (local-network discovery plus a
  manual URL), initializes the database, and optionally runs import and enrichment. Non-setup
  pages (dashboard, recommend, playlists) redirect back here while the library is missing or
  empty.
- **Settings** (`/settings`): a persistent view for Plex URL/token/library, the MusicSeed
  database path, Spotify credentials, and the local sonic-vector import action. Saving persists
  config without starting any import, enrichment, or database initialization.
- **Plex discovery**: local-network discovery is passive and read-only — GDM multicast on
  `239.0.0.250:32414` with an SSDP fallback on `239.255.255.250:1900`
  (`urn:plex-com:service:pms:1`), stdlib-only. Multicast never crosses routers, so servers on
  other subnets are found via `plex.tv/api/resources` when a Plex token is configured.

Relevant API routes: `GET /discovery`, `GET /discovery/plex-servers`,
`POST /discovery/check`, `POST /discovery/config` (save-only), `POST /discovery/init-db`.

### Ports

`musicseed` listens on `127.0.0.1:8789` (JSON at `/api`, UI at `/`). Contributor `dev.sh`
adds Next.js on `127.0.0.1:3000` and reads `API_PORT`, `WEB_PORT`, and `API_URL` from the
environment. Both bind loopback only.

### Offline behavior

The web UI and API are fully local and need no internet once the app is running. Internet access
is required only for enrichment providers (ListenBrainz, and optional Spotify) and for the
cross-subnet Plex lookup through `plex.tv`; without it, discovery falls back to local-network
multicast and a manual URL, and enrichment is simply skipped for tracks it can't reach.

## Logging

The CLI configures file logging through `core/src/musicseed/logging_config.py`.

- Timestamped run logs: `~/.local/share/musicseed/logs/musicseed_YYYYMMDD_HHMMSS.log`
- Latest run: `~/.local/share/musicseed/logs/latest.log`

When changing pipelines, log enough detail to diagnose failed batches without flooding console
output. Console output should summarize progress and outcome.

## Safe Development Commands

These are cheap and should be used before heavier checks:

```bash
python3 -m compileall -q core/src/musicseed cli/src/musicseed_cli api/src/musicseed_api
uv run ruff check src
uv run musicseed-cli --help
```

Stateful commands should be limited during development:

```bash
uv run musicseed-cli enrich --source listenbrainz --limit 100 --batch-size 50 --resume
uv run musicseed-cli sonic-probe
uv run musicseed-cli recommend --seed-id 123 --limit 20 --dry-run --explain
```

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
