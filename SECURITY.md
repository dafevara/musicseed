# Security Policy

## Supported versions

MusicSeed is a personal, local-first project. Security fixes are applied on a
best-effort basis to the latest commit on the default branch. There is no
long-term support window for older tags.

## What this project handles

MusicSeed may hold, on the machine where it runs:

- A Plex Media Server API token (playlist create/update)
- Paths to the local Plex SQLite databases and music files
- Optional Spotify client credentials
- Library metadata and play history (in the local SQLite database file)

MusicSeed is designed to keep that data **local**. It does not upload your
library catalog to a MusicSeed-operated service. Optional outbound calls go only
to APIs you configure (e.g. ListenBrainz, Spotify, Plex).

## Reporting a vulnerability

**Do not open a public GitHub issue for security problems**, especially if the
report might include tokens, credentials, paths to private libraries, or log
excerpts that contain secrets.

Prefer one of:

1. **GitHub private vulnerability reporting** on this repository (Security →
   Report a vulnerability), once the repo is public and reporting is enabled.
2. **Email the maintainer** listed in `pyproject.toml` / GitHub profile, with
   subject line `[MusicSeed security]`.

Please include:

- A clear description of the issue and impact
- Steps to reproduce (minimal, no real secrets)
- Affected commit or tag if known
- Whether you have a suggested fix

You should receive an acknowledgment when the maintainer is available. There is
no SLA; this is a single-maintainer home project.

## What not to include in issues or PRs

Never paste into public issues, PRs, discussions, or screenshots:

- Plex tokens (`X-Plex-Token`, `plex.token`)
- Spotify `client_id` / `client_secret`
- Database passwords
- Full paths that identify your home directory or private library layout
  (redact to placeholders like `~/Music/...`)
- Raw `logs/` or `latest.log` content without redaction
- Contents of `config.yaml`, `.env`, or local database dumps

## Safe defaults for operators

- Copy `config.example.yaml` to a local config path (see README); never commit
  a real `config.yaml`.
- Prefer the Plex account sign-in (setup wizard, Settings, or
  `musicseed-cli plex-login`) over handling tokens by hand: the token is obtained
  from plex.tv, validated, and written straight to `config.yaml`. The file is
  written owner-only (`0600`).
- Prefer environment-variable placeholders (`${PLEX_TOKEN}`) over hard-coded
  secrets in YAML.
- Keep `config.yaml`, `.env`, `data/`, `logs/`, and `*.db` out of git (see
  `.gitignore`).
- The MusicSeed database is a local SQLite file containing your listening
  history. Keep it on your machine, out of git, and out of shared backups.
- Treat Plex tokens as account credentials; rotate them if they leak.
- Do not run MusicSeed against a Plex server or database you do not own or
  administer.

## Browser protections

The web API and the MCP HTTP transports apply browser protections on every
request. The MCP server (``streamable-http``/``sse``) uses the SDK's built-in
DNS-rebinding protection on loopback, and enforces ``security.allowed_hosts``
on a non-loopback bind.

- **Host allowlist** — requests whose ``Host`` header names an unexpected
  hostname are rejected (blocks DNS rebinding). Loopback and private
  (home-LAN) addresses are allowed by default; add ``security.allowed_hosts``
  entries for a home-network DNS name.
- **Origin check** — state-changing requests whose ``Origin``/``Referer``
  names an unrelated website are rejected.
- **CSRF token** — browser-driven writes must include an ``X-MusicSeed-CSRF``
  header obtained from ``GET /security/csrf``. Non-browser clients (CLI, curl,
  MCP) are exempt.

These protections keep a trusted home-LAN surface usable without accounts.
They are **not** authentication: any client that can reach the server can
still exercise MusicSeed's permissions (Plex playlists, enrichment, import).
Only expose the server on a network you trust. If you expose it to a public or
untrusted network, put an authenticating reverse proxy (or the equivalent) in
front of it — MusicSeed does not ship a login.

## Credential routing

An SSH password is bound to its SSH target: probing a *different* target sends
no stored password, and changing the configured target clears the password
unless a new one is supplied in the same submission, so changing servers cannot
silently re-send a password elsewhere. The Plex token is account-wide, so
selecting a different server on the same account keeps it — and the server
picker verifies candidate addresses without sending any token.

## Transport encryption

Local, home-LAN, and VPN ``http://`` Plex connections are supported — loopback,
RFC1918 private, link-local, CGNAT/Tailscale (``100.64.0.0/10``), IPv6 ULA, and
``.local``/``.home.arpa``/``.ts.net`` hostnames. A plain ``http://`` connection
to a *globally routable* host would send the Plex token in cleartext, so
MusicSeed refuses it unless ``plex.allow_cleartext_remote`` is set explicitly —
prefer ``https://`` or a VPN/tunnel. HTTPS keeps certificate verification
enabled (httpx defaults); it is never disabled.

## Private file handling

- The config file is written owner-only (``0600``) from its very first write:
  it is dumped to an owner-only temp file in the same directory and atomically
  moved into place, so an interruption cannot leave a half-written config.
- The MusicSeed SQLite database is created owner-only (``0600``); its WAL/SHM
  sidecars inherit that mode.
- Log files are created owner-only (``0600``) before their first write, and a
  redaction filter replaces any configured token/secret that reaches a log line
  with ``[REDACTED]``.

## Resource limits

Expensive work is bounded by default and can be raised deliberately via the
``limits`` config section for large libraries: request body size, seed count,
approved selection size, typeahead/recommendation result counts, and the total
size of a remote Plex database snapshot (which is also refused when the
destination lacks free disk space). Plex sonic-vector blobs are decompressed
under a fixed per-blob cap, so a malformed blob cannot expand into a zip bomb.

## Installations and releases

- CI covers every app (core, cli, api, and mcp), runs a per-app dependency
  audit (``uv audit``), a gitleaks secret scan, and an ``npm audit`` on a
  schedule and on every push/PR.
- CI actions are pinned to immutable commit SHAs.
- Releases are only cut after the ``CI`` workflow passes on ``main`` (or via an
  explicit manual dispatch).
- End-user installs (``scripts/install.sh``) install against a pinned,
  CI-tested dependency set (``constraints.txt``), regenerated from the
  lockfiles with ``scripts/export-constraints.sh``.

## Scope notes

Out of scope for security reports unless they create a concrete local exploit:

- Recommendation quality / scoring behavior
- Missing features or documentation gaps
- Rate limits or availability of third-party APIs (ListenBrainz, Spotify, Plex)

In scope examples:

- Secrets written into tracked files or logs by default
- Command injection or path traversal when resolving configured paths
- Unintended network exposure of tokens or library paths
