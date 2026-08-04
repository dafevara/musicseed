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
- Prefer environment-variable placeholders (`${PLEX_TOKEN}`) over hard-coded
  secrets in YAML.
- Keep `config.yaml`, `.env`, `data/`, `logs/`, and `*.db` out of git (see
  `.gitignore`).
- The MusicSeed database is a local SQLite file containing your listening
  history. Keep it on your machine, out of git, and out of shared backups.
- Treat Plex tokens as account credentials; rotate them if they leak.
- Do not run MusicSeed against a Plex server or database you do not own or
  administer.

## Scope notes

Out of scope for security reports unless they create a concrete local exploit:

- Recommendation quality / scoring behavior
- Missing features or documentation gaps
- Rate limits or availability of third-party APIs (ListenBrainz, Spotify, Plex)

In scope examples:

- Secrets written into tracked files or logs by default
- Command injection or path traversal when resolving configured paths
- Unintended network exposure of tokens or library paths
