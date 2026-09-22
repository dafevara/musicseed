---
name: musicseed-playlists
description: Create and populate Plex playlists with MusicSeed recommendations over MCP. Use when a user asks to make a new playlist from seed tracks, extend an existing playlist with similar tracks, or otherwise manage playlists through MusicSeed. Covers seed resolution, previews, the approve-then-write contract, weight presets, and failure handling.
---

# MusicSeed playlist management

You drive MusicSeed through its MCP tools. MusicSeed generates Plex playlists
from seed tracks using six signals (sonic, popularity, style, genre, era,
novelty) over the user's local library. You orchestrate the workflow; all
recommendation and write logic lives behind the tools.

## Workflow

New playlist:

1. **Resolve seeds.** Users name tracks in free text. Call `search_tracks` for
   each name and pick the correct local `id`. When a name is ambiguous
   (multiple artists/versions), show the candidate matches and ask the user
   which they meant — do not guess.
2. **Preview.** Call `preview_playlist` with the resolved `seed_ids`. It
   returns scored recommendations with per-signal breakdowns. It never writes.
3. **Approve.** Present the seed tracks and a short, readable list of
   recommendations to the user. Get explicit approval of the specific tracks.
4. **Write once.** Call `create_playlist` with `seed_ids` (the seeds, kept
   first) and `track_ids` (only the approved recommendation IDs). Never invent
   IDs that were not in the preview.

Existing playlist:

1. `list_playlists` to find the playlist's `rating_key` (never its title).
2. `preview_populate` to score complementary tracks. It never writes.
3. Approve a subset with the user.
4. `populate_playlist` with only the approved `track_ids`.

## Hard rules

- **Approve before you write.** `create_playlist` and `populate_playlist` write
  to Plex. Only pass IDs that were shown in a preview and approved by the user.
  A model deciding the user would approve is not approval.
- **Writes are exact and idempotent.** Core validates the full selection before
  writing and rejects stale/missing IDs. Retrying after a timeout is safe:
  already-present tracks are not re-added and are reported in
  `already_present_count`; re-creating the same playlist returns the existing
  one. If a write returns an error, do not blindly repeat it — inspect the
  error and re-preview if the selection is stale.
- **Playlists are identified by `rating_key`, not title.** Two playlists can
  share a title.

## Weight presets

Use `list_presets`; pass a preset name (`balanced`, `sonic`, `discovery`,
`popular`) rather than raw weights. `balanced` is the default.

## Natural language limits

Natural language does not add recommendation capabilities. There is no "mood"
signal. "Make an energetic playlist for a rainy evening" cannot be scored
directly. Map such requests onto concrete seeds and a preset, and tell the user
what you used. If the user gives no seeds, ask for example tracks or artists —
do not fabricate a seed.

## Failure handling

- Missing/empty library: call `get_status` first; if `track_count` is 0, tell
  the user to import their library (the web UI or CLI `import` command does
  this) before asking for playlists.
- No matches for a seed: report it plainly and ask for a different name rather
  than substituting a near-match.
- A write fails: surface the exact error. Do not retry the write in a loop;
  reconcile first.
