# Core Runtime and Models

`MusicSeedContext` owns a resolved config, a lazy SQLite engine/session factory, and the local
sonic-vector cache. Pass `context=` to services to isolate an operation. `use_context` binds
legacy helpers to an operation; otherwise they use the process default. Changing default config
resets that default context. Background jobs capture a deep copy so a config change cannot
redirect a running job to a different database.

Vectors come from `track_vectors`, not Plex source files during recommendation. Cached vectors
check `runtime_state.sonic_generation`, incremented by each committed import batch. See
[local runtime](../infra/local-runtime.md) for writer claims, import provenance, and recovery.

## Context

::: musicseed.context

## Configuration

::: musicseed.config

## Service DTOs

::: musicseed.services.schemas

## Exceptions

::: musicseed.exceptions

## Database sessions and schema compatibility

::: musicseed.db.session

## Database models

::: musicseed.db.models

## Sonic vectors

::: musicseed.sonic

## Plex database snapshots

::: musicseed.plex_db_source
