# Core Services

Surface-agnostic business logic from `musicseed-core` (`musicseed.services.*`). These services
return result models and raise typed exceptions; CLI, API handlers, and MCP adapters map them.
Database-backed operations accept an optional `MusicSeedContext`; see
[runtime and models](core-runtime.md) for configuration, sessions, vector caching, and DTOs.

Recommendation results contain scalar `ServiceTrack` / `ServiceRecommendation` models, so they
remain JSON-serializable after the service closes its session. For a preview/approval workflow,
write the approved IDs with `playlist_tracks.create_playlist_from_tracks` or
`populate.populate_playlist(track_ids=...)`. `recommend.create_playlist` and populate without
`track_ids` are separate generate-and-write paths; they must not replace an approved selection.

## Library

::: musicseed.services.library

## Recommend

::: musicseed.services.recommend

## Approved playlist selections

::: musicseed.services.playlist_tracks

## Enrichment

::: musicseed.services.enrichment

## Discovery

::: musicseed.services.discovery

## Plex Discovery

::: musicseed.services.plex_discovery

## Populate

::: musicseed.services.populate

## Plex Analysis

::: musicseed.services.plex_analysis

## Local sonic vector import

::: musicseed.services.sonic_vectors

## Dashboard

::: musicseed.services.dashboard

## Jobs

::: musicseed.services.jobs

## Import provenance

::: musicseed.services.import_state

## Typeahead

::: musicseed.services.typeahead

## Offline evaluation

::: musicseed.services.evaluation
