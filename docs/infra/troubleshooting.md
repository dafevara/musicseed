# Troubleshooting

Concrete checks and recovery actions for the most common MusicSeed setup and job failures. Read
[`local-runtime.md`](local-runtime.md) for how the pieces fit together, then use this doc when
something misbehaves.

## First: get a read on the system

Before guessing, capture the current state with the two cheapest probes:

- **From the web UI:** the setup wizard and dashboard already render discovery results and job
  state. The underlying JSON is available directly at
  `curl http://127.0.0.1:8789/api/discovery` — it reports, for each required local file and the Plex
  server, a machine-readable `reason` code plus `missing_inputs` (keys like `plex_token`,
  `plex_unreachable`, `plex_library`, `plex_db_path`, `db_location`, `enrichment_credentials`) and a
  derived `first_run` status (`no_config` / `db_missing` / `library_empty` / `import_incomplete`).
- **From the CLI:** `musicseed-cli status` shows the resolved database path, Plex URL/DB/library,
  and library/enrichment coverage.

Logs are the next stop: `~/.local/share/musicseed/logs/latest.log` (plus timestamped
`musicseed_*.log` in the same directory). Jobs that fail mid-flight write the exception there.

## Plex server not found

Symptom: the setup wizard shows no discovered server, or discovery reports
`plex_unreachable` in `missing_inputs`.

Checks and recovery:

1. **Local subnet.** GDM/SSDP multicast never crosses routers, so discovery only finds servers on
   the same subnet. Sign in with your Plex account so MusicSeed can look up your servers via
   `plex.tv/api/resources` — or enter the server URL manually in the wizard.
2. **Pick an address that answers.** A Plex server advertises several addresses (its own LAN
   interfaces, a VPN/Tailscale address, a `plex.direct` hostname), and the ones Plex prefers are
   often unreachable from another machine. The picker probes each one and labels it: choose an
   entry marked **reachable** (they are sorted first), and the current address is marked
   **in use**. An address that only works on the server's own network will always report
   `unreachable`, no matter what the server is doing.
3. **Enter the URL manually.** The wizard and Settings accept an explicit Plex URL
   (e.g. `http://<plex-host>:32400`). Use the IP or hostname where Plex actually listens, and
   remember that the field shows the URL currently being probed — edit it if it is wrong.
4. **Confirm Plex is up.** Verify Plex responds at `http://127.0.0.1:32400/identity` from the same
   machine. Firewalls or a VPN that filters multicast/SSDP will hide the server from discovery but
   not from a manual URL.
5. **Library name.** Discovery reports `library_not_found` when the server is reachable but the
   configured music library name doesn't match a section. Check the exact library name in Plex
   settings and re-enter it.

## Plex sign-in / permission failures

Symptom: `unauthorized`, `missing_token`, or `plex_token` in `missing_inputs`; Plex API calls
return 401.

Checks and recovery:

1. **Sign in with Plex.** In the wizard's **Connect Plex** step (or Settings), choose
   **Sign in with Plex**. Your browser goes to Plex's own sign-in page, and the token it returns
   is validated against plex.tv and saved locally — nothing to copy. Setup advances to
   **Review & initialize** once the connection succeeds.
2. **No browser on this machine (server/NAS/Docker).** Run `musicseed-cli plex-login` where
   MusicSeed is installed: it prints a short code to enter at `https://plex.tv/link`. Use
   `--open` when a browser *is* available. `musicseed-cli plex-logout` forgets the stored token.
3. **Auto-detection.** When Plex runs on the same machine as MusicSeed, nothing may be needed at
   all: MusicSeed reads the token from Plex's local install (macOS
   `~/Library/Application Support/Plex Media Server/Preferences.xml`, or the Linux Plex data dir →
   `PlexOnlineToken`, falling back to `.LocalAdminToken`).
4. **plex.tv unreachable.** Offline installs cannot use the sign-in flow at all. Open
   **Advanced: paste a Plex token instead** in the wizard/Settings and paste one: from a
   signed-in session at app.plex.tv, view any Plex XML resource and copy the `X-Plex-Token`
   query parameter.
5. **Finding the local Plex library and blobs databases does not authenticate the Plex
   connection.** A token (or sign-in) is needed to write playlists to Plex; local import and
   recommendations can work without it. Choose **Continue without Plex connection** to set those
   up first, then connect Plex from the review step or Settings when you're ready.
6. **Scope.** `.LocalAdminToken` works only for localhost requests. If you access Plex over the
   network, sign in (or use `PlexOnlineToken`) instead.
7. **Where tokens live.** Tokens are stored in `config.yaml` (written owner-only, `0600`), not in
   the database. They are sent in POST bodies and never rendered back to the UI — the UI shows only
   "configured / not set". Revoking MusicSeed in Plex's **Authorized Devices** page invalidates the
   stored token; sign in again (or run `plex-login`) to replace it.

## Plex database import over SSH

Symptom: the wizard's **Plex library database** check fails on a remote Plex host, the import
stops before downloading anything, or `scp` works from a terminal while MusicSeed does not.

Checks and recovery:

1. **Target shape.** Enter `[user@]host:/path` for the folder that holds
   `com.plexapp.plugins.library.db`. Pasting the database **file's** own path is accepted too (its
   folder is used). `~` is expanded on the remote host, quotes around the target or the path are
   stripped, spaces need no escaping, and a trailing slash is ignored — so an `scp` command line
   can be pasted as is.
2. **Authentication is non-interactive.** paramiko never prompts, so a key that only exists in
   your terminal's agent is invisible to a MusicSeed process without `SSH_AUTH_SOCK`. Run
   `ssh-add`, and make sure whatever starts MusicSeed (shell, `systemd` unit, `launchd` agent,
   container) inherits `SSH_AUTH_SOCK` — or set `plex.db_ssh_password`. MusicSeed reports
   authentication failure with exactly that guidance.
3. **Remote prerequisites.** The host needs `python3` with the standard-library `sqlite3` module,
   read access to Plex's `Databases` folder, and free temporary space for both backups.
4. **Read the reported reason.** The bundled helper returns one code, mapped to a message:
   `not_found` (nothing at that path), `not_a_directory` (the path is a file that is not a Plex
   database), `database_not_found` (the folder exists but has no library database),
   `unreadable` (permissions, or SQLite cannot open it), `timeout` (backup exceeded five minutes —
   retry when Plex is idle). Tracebacks and host paths are never shown; run the helper by hand on
   the host when you need the raw error.
5. **Host trust.** First connect once as the same local OS user that runs MusicSeed so the key is
   in that user's `~/.ssh/known_hosts`. Unknown or changed host keys fail closed — verify the
   fingerprint independently, never bypass the warning. MusicSeed does not read `~/.ssh/config`
   aliases, so supply the real host, user, and port.
6. **After a failure.** The previous published snapshot is kept, so status and recommendations
   keep working. Never copy live `-wal`/`-shm` files (or a raw copy of a running server's
   database) into the cache to repair it; run the import again instead.
7. **Is it stuck?** The refresh reports real percentages: `preparing Plex snapshot` covers the
   host's own SQLite backups (no data moves during it, and it takes minutes for a large library),
   then `downloading Plex database` / `downloading Plex sonic-vector database` cover the
   transfer. Watch for movement: a percentage that climbs is working; one that never leaves 0%
   (or a `timeout` code) is not. Each database has a five-minute backup budget on the host.

## Occupied ports

Symptom: `musicseed` (or contributor `dev.sh`) fails with "address already in use".

Recovery:

1. The product server defaults to `127.0.0.1:8789`. Contributor `dev.sh` also uses `:3000` (web) and `:8790` (MCP).
2. Free the port: `lsof -i :8789` (or `:3000`) to find the process, then stop it — or pick a
   new port with `musicseed --port <n>`. `dev.sh` reads `API_PORT`, `WEB_PORT`, `API_URL`, and `MCP_PORT`.
3. If you change the API port under `dev.sh`, point the web proxy at it with
   `API_URL=http://127.0.0.1:<new>`.

## Interrupted jobs (import / enrichment / playlist preview)

Symptom: the dashboard shows a failed/interrupted job, or a long job stopped partway (Ctrl-C,
crash, or machine sleep).

Recovery:

- **Import** is incremental by default and resumable: re-running it (`POST /api/library/import` on the product server, or
  `musicseed-cli import`) continues where it left off. Use `--full` (CLI) only when you intend a
  complete re-import.
- **Enrichment** marks attempted tracks, so re-running with resume
  (`musicseed-cli enrich --source listenbrainz --resume`) skips already-attempted tracks.
- **Playlist preview** shows a spinner while calculating and displays results without a refresh.
  A page refresh reconnects to the same calculation. If the API restarts during work, use
  **Retry calculation**; unfinished calculations restart from the beginning and do not change
  Plex playlists. Completed preview results survive API restarts until their job is deleted.
- **Cancel vs. delete.** Cancellation is cooperative and keeps the writer reserved until the
  target returns. Already-committed batches remain; active/cancel-requested rows cannot be deleted.
  Settings changes and new imports are rejected while that writer is active.
- **Restart recovery.** On job-system startup/submission or a status poll, pending/running/cancel-requested jobs
  owned by dead processes become interrupted. Live owners are never forcibly displaced. The
  liveness check is PID-based and conservative. If a stale PID has been reused, do not kill an
  unrelated process to clear the claim; stop MusicSeed and inspect the job record before manual
  repair.
- **Calculation cancellation** reserves its separate preview slot until the worker returns.
  The UI waits before submitting replacement parameters; imports can still use the writer slot.
  Settings changes wait for both kinds of active jobs.
- **Import provenance.** Completion belongs to the source and library, not a successful job row.
  Deleting history cannot make setup incomplete again. Older installations without provenance
  should run an incremental import once; unknown coverage is not a verified complete import.
- **SQLite lock contention** can occur when another writer holds the file. MusicSeed serializes
  its import/enrichment services, but external tools can still contend. Stop competing writers,
  then retry. Do not delete WAL/SHM files to resolve contention.
- Failed jobs keep their completed work; the dashboard shows an actionable summary and points at
  the log rather than rendering a traceback.

## Provider failures / rate limits (enrichment)

Symptom: enrichment succeeds only partially, or ListenBrainz/Spotify calls fail or slow to a crawl.

Checks and recovery:

- **ListenBrainz is the preferred source** and keys off recording MBIDs. It requires a free user
  token (from https://listenbrainz.org/settings/, set as `listenbrainz.token` in config or via
  Settings); authenticated requests get higher rate limits. Tracks without
  a MusicBrainz ID cannot be enriched via ListenBrainz — that's expected, not an error. `status`
  shows MBID coverage.
- **Spotify is a credentialed fallback** and uses text matching. If it isn't configured,
  Spotify enrichment is skipped; nothing else needs Spotify.
- **Rate limits.** Both providers are rate-limited. The pipeline uses bounded concurrency and
  retries; if a provider is throttling you, re-run with a smaller `--batch-size`/`--concurrency`
  and `--resume` rather than starting over.
- **Enrichment credentials.** Enrichment requires either a ListenBrainz user token
  (`listenbrainz.token`) or Spotify credentials (`spotify.client_id` / `spotify.client_secret`).
  Add them in Settings or `config.yaml`.

## Missing sonic analysis

Symptom: recommendations feel random, or the dashboard shows low sonic coverage.

Checks and recovery:

- **Sonic vectors are imported from Plex into the local store.** MusicSeed copies vectors into its
  `track_vectors` table (`musicseed-cli import-plex-sonic`) and reads them from there; the blobs
  database is only needed at import time. If `import-plex-sonic` fails with "sonic ... unavailable",
  the Plex blobs database path isn't resolvable — fix it in Settings.
- **Import fails with "Snapshot … is unreadable: unknown tokenizer: collating" (or "no such
  collation sequence").** Plex's library database declares FTS tables with custom tokenizers
  (`tokenize=collating`) and indexes with custom collations (`icu_root`) that only Plex's own
  SQLite runtime can resolve, so stock SQLite cannot run whole-database integrity checks on a
  snapshot. MusicSeed tolerates this (the file is still validated for completeness and the
  vectors themselves read fine), so the import should proceed; if an older version surfaced
  this error, upgrade and re-run the import.
- **Canceled vector import:** committed batches (500 vectors by default) remain available.
  Rerun `musicseed-cli import-plex-sonic` to refresh/finish; existing IDs are updated rather than
  duplicated. Progress/cancellation happen between commits, not during snapshot transfer or
  source decoding. Other API/CLI contexts refresh cached vectors on their next access.
- **Check coverage:** `musicseed-cli sonic-probe` reports analyzed vs. unanalyzed tracks and the
  albums still pending.
- **Trigger analysis:** `musicseed-cli sonic-refresh` runs Plex's MusicAnalysis Butler task. It
  processes Plex's *entire* pending backlog (CPU-heavy) and keeps running after the command
  finishes; the command prompts for confirmation first. `sonic-probe --trigger-butler` tests the
  Butler path while watching one album, but also starts the whole pending backlog; it is not
  an album-scoped analysis request.
- Tracks Plex has not analyzed still participate in recommendation — they get a neutral sonic
  score (0.5) and rank on the other five signals. So partial coverage is a quality issue, not a
  blocker.

## Database backup and recovery

- **Backup = copy the file.** MusicSeed state is one SQLite file (default
  `~/.local/share/musicseed/musicseed.db`). Copy it after a clean shutdown of every API/CLI
  process. If a WAL remains after an interrupted shutdown, or MusicSeed must stay running,
  use SQLite's online backup API or `.backup` command. Sequentially copying a live database
  and its `-wal`/`-shm` sidecars does **not** produce a guaranteed consistent backup.
- **Restore** by copying the file back. If the file is corrupt or you want a clean start, stop the
  API/CLI, move the file aside, and run setup again (the wizard re-runs when the database is
  missing — the `db_missing` first-run signal).
- **Rebuilding restores derived library data, not every local record.** A fresh `init-db` +
  `import` + `import-plex-sonic` + `enrich` can reconstruct metadata, vectors, and popularity,
  but does not restore old job history or completion records. Keep a backup before rebuilding.
  Enrichment requires third-party API calls, which is why resuming beats re-fetching.

## Logs and where to look

- `~/.local/share/musicseed/logs/latest.log` — CLI, `musicseed` (API/UI), and MCP append here.
  Follow with `tail -f ~/.local/share/musicseed/logs/latest.log`.
  Set `MUSICSEED_LOG_LEVEL=DEBUG` (or `--log-level` on the CLI) to raise verbosity.
- `~/.local/share/musicseed/logs/musicseed_YYYYMMDD_HHMMSS.log` — timestamped per-process run.

If an error message says "check logs/latest.log", the exception detail is there. Avoid sharing
those logs outside the machine — they can contain local paths and, in rare cases, credentials.
