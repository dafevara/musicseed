# Product Overview

MusicSeed helps one owner get better discovery from an existing Plex music library.

## User

The intended user is a technically comfortable music collector running Plex locally, with a large
library and a preference for CLI tools. The project assumes the user can start local services,
provide API credentials, and inspect logs.

## Product Promise

Given one or more seed tracks, MusicSeed should recommend tracks already in the user's collection
that match the desired feel while still surfacing useful discovery candidates.

Good recommendations should be:

- Local: only recommend tracks from the imported Plex library.
- Explainable: show why a track ranked well when `--explain` is used.
- Tunable: let weights and constraints change without code edits.
- Recoverable: long jobs can be rerun with resume or missing-only behavior.
- Practical: prefer working playlist output over perfect music intelligence.

## Goals

- Import Plex music metadata and play history.
- Reuse MusicBrainz IDs already present in Plex when available.
- Prefer ListenBrainz popularity because it works from MBIDs and avoids search ambiguity.
- Use Spotify as an optional fallback when credentials are configured.
- Use Plex's sonic analysis vectors for sonic similarity (read at query time; MusicSeed generates
  no embeddings of its own).
- Rank candidates from multiple signals instead of trusting one source.
- Preview recommendations with `recommend`, or create a Plex playlist interactively with `playlist`.

## Non-Goals

- Public SaaS, multi-user support, or horizontal scalability.
- Replacing Plex, Plexamp, or the user's music file organization.
- Real-time recommendation serving.
- Web UI or mobile app for v1.
- Perfect external catalog matching.
- Complex observability stacks, queues, distributed workers, or hosted deployment.

## Product Guardrails

- Keep defaults conservative and local.
- Do not make full-library jobs accidental. Development examples should use `--limit`.
- Any command that writes to Plex should have an easy dry-run path nearby.
- Console output should answer what happened and where to inspect details.
- Avoid hidden magic. Music recommendation behavior should be traceable from seed resolution,
  candidate sources, score breakdowns, and selection constraints.

## Current User Flows

1. Initialize the local database (`init-db` creates the SQLite file) and optimize the schema.
2. Import Plex metadata.
3. Enrich ListenBrainz popularity for MBID-backed tracks.
4. Optionally enrich Spotify metadata.
5. Ensure Plex has sonically analyzed the library (`sonic-probe` to check, `sonic-refresh` to trigger).
6. Run `recommend` with seed text or seed IDs to preview the list.
7. Run `playlist --name "My Playlist"` with the same parameters to approve and create it in Plex.
