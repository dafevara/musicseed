# Troubleshooting

Concrete checks and recovery actions for the most common MusicSeed setup and job failures. Read
[`local-runtime.md`](local-runtime.md) for how the pieces fit together, then use this doc when
something misbehaves.

## First: get a read on the system

Before guessing, capture the current state with the two cheapest probes:

- **From the web UI:** the setup wizard and dashboard already render discovery results and job
  state. The underlying JSON is available directly at
  `curl http://127.0.0.1:8789/discovery` — it reports, for each required local file and the Plex
  server, a machine-readable `reason` code plus `missing_inputs` (keys like `plex_token`,
  `plex_unreachable`, `plex_library`, `plex_db_path`, `db_location`, `enrichment_credentials`) and a
  derived `first_run` status (`no_config` / `db_missing` / `library_empty`).
- **From the CLI:** `musicseed-cli status` shows the resolved database path, Plex URL/DB/library,
  and library/enrichment coverage.

Logs are the next stop: `~/.local/share/musicseed/logs/latest.log` (plus timestamped
`musicseed_*.log` in the same directory). Jobs that fail mid-flight write the exception there.

## Plex server not found

Symptom: the setup wizard shows no discovered server, or discovery reports
`plex_unreachable` / `missing_inputs` includes `plex_server`.

Checks and recovery:

1. **Local subnet.** GDM/SSDP multicast never crosses routers, so discovery only finds servers on
   the same subnet. If Plex runs on a different subnet, supply a Plex token so MusicSeed can look
   up your servers via `plex.tv/api/resources` — or enter the server URL manually in the wizard.
2. **Enter the URL manually.** The wizard and Settings accept an explicit Plex URL
   (e.g. `http://<plex-host>:32400`). Use the IP or hostname where Plex actually listens.
3. **Confirm Plex is up.** Verify Plex responds at `http://127.0.0.1:32400/identity` from the same
   machine. Firewalls or a VPN that filters multicast/SSDP will hide the server from discovery but
   not from a manual URL.
4. **Library name.** Discovery reports `library_not_found` when the server is reachable but the
   configured music library name doesn't match a section. Check the exact library name in Plex
   settings and re-enter it.

## Token / permission failures

Symptom: `unauthorized`, `missing_token`, or `plex_token` in `missing_inputs`; Plex API calls
return 401.

Checks and recovery:

1. **Auto-detection.** MusicSeed reads the token from Plex's local install
   (macOS `~/Library/Application Support/Plex Media Server/Preferences.xml`, or the
   Linux Plex data dir →
   `PlexOnlineToken`, falling back to `.LocalAdminToken`). If neither is present (or Plex isn't
   installed locally), paste a token manually.
2. **Get a token.** From a signed-in session at app.plex.tv, view any Plex XML resource and copy
   the `X-Plex-Token` query parameter. The wizard/Settings shows this guidance when no token is
   found.
3. **Scope.** `.LocalAdminToken` works only for localhost requests. If you access Plex over the
   network, use `PlexOnlineToken` (a full token) instead.
4. **Where tokens live.** Tokens are stored in `config.yaml`, not in the database. They are sent in
   POST bodies and never rendered back to the UI — the UI shows only "configured / not set".

## Occupied ports

Symptom: `musicseed` (or contributor `dev.sh`) fails with "address already in use".

Recovery:

1. The product server defaults to `127.0.0.1:8789`. Contributor `dev.sh` also uses `:3000`.
2. Free the port: `lsof -i :8789` (or `:3000`) to find the process, then stop it — or pick a
   new port with `musicseed --port <n>`. `dev.sh` reads `API_PORT`, `WEB_PORT`, and `API_URL`.
3. If you change the API port under `dev.sh`, point the web proxy at it with
   `API_URL=http://127.0.0.1:<new>`.

## Interrupted jobs (import / enrichment)

Symptom: the dashboard shows a failed/interrupted job, or a long job stopped partway (Ctrl-C,
crash, or machine sleep).

Recovery:

- **Import** is incremental by default and resumable: re-running it (`POST /library/import`, or
  `musicseed-cli import`) continues where it left off. Use `--full` (CLI) only when you intend a
  complete re-import.
- **Enrichment** marks attempted tracks, so re-running with resume
  (`musicseed-cli enrich --source listenbrainz --resume`) skips already-attempted tracks.
- **Cancel vs. delete.** The dashboard can cancel a running job (at the next safe batch boundary)
  or delete a finished/failed job record. Cancelling leaves already-committed batches in place.
- **SQLite lock contention** is the usual cause of a crash mid-job (e.g. a stale `-wal`/`-shm`
  sidecar while another process holds the file). Stop other MusicSeed processes, then retry the job.
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

- **Sonic vectors are read from Plex at query time.** MusicSeed stores nothing; Plex must have
  analyzed the library. If `recommend` fails with "sonic ... unavailable", the Plex blobs database
  path isn't resolvable — fix it in Settings.
- **Check coverage:** `musicseed-cli sonic-probe` reports analyzed vs. unanalyzed tracks and the
  albums still pending.
- **Trigger analysis:** `musicseed-cli sonic-refresh` runs Plex's MusicAnalysis Butler task. It
  processes Plex's *entire* pending backlog (CPU-heavy) and keeps running after the command
  finishes; the command prompts for confirmation first. `sonic-probe --trigger-butler` tests the
  Butler path on one album before committing to it.
- Tracks Plex has not analyzed still participate in recommendation — they get a neutral sonic
  score (0.5) and rank on the other five signals. So partial coverage is a quality issue, not a
  blocker.

## Database backup and recovery

- **Backup = copy the file.** MusicSeed state is one SQLite file (default
  `~/.local/share/musicseed/musicseed.db`). Copy it while MusicSeed is stopped; if it must stay
  running, also copy the `-wal` and `-shm` sidecars, or use SQLite's online backup.
- **Restore** by copying the file back. If the file is corrupt or you want a clean start, stop the
  API/CLI, move the file aside, and run setup again (the wizard re-runs when the database is
  missing — the `db_missing` first-run signal).
- **Rebuilding is safe and idempotent.** The database is derived from Plex metadata; a fresh
  `init-db` + `import` + `enrich` reconstructs it. Enrichment is the only step that spends
  third-party API calls, which is why resuming beats re-fetching.

## Logs and where to look

- `~/.local/share/musicseed/logs/latest.log` — CLI and `musicseed` (API/UI) append here.
  Follow with `tail -f ~/.local/share/musicseed/logs/latest.log`.
  Set `MUSICSEED_LOG_LEVEL=DEBUG` (or `--log-level` on the CLI) to raise verbosity.
- `~/.local/share/musicseed/logs/musicseed_YYYYMMDD_HHMMSS.log` — timestamped per-process run.

If an error message says "check logs/latest.log", the exception detail is there. Avoid sharing
those logs outside the machine — they can contain local paths and, in rare cases, credentials.
