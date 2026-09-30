# API Handlers

Surface-agnostic orchestration from `musicseed-api` (`musicseed_api.handlers.*`). Handlers call
core services, manipulate config, manage job lifecycles, and map errors; routes stay thin.

The web UI calls these handlers through HTTP; the CLI and MCP call core services directly.
Handlers are framework-free, synchronous functions. Routes parse form/query inputs and the app
maps typed core exceptions to HTTP responses.

See the [HTTP API guide](http-api.md) for URL prefixes, request encoding, and the live OpenAPI
schema (`/api/openapi.json` with `musicseed`, `/openapi.json` with `musicseed --no-ui`).
The playlist handlers retain programmatic generate-and-write paths, but HTTP create/populate
routes always require approved `track_ids`.

## Recommend

::: musicseed_api.handlers.recommend

## Library

::: musicseed_api.handlers.library

## Discovery

::: musicseed_api.handlers.discovery

## Enrichment

::: musicseed_api.handlers.enrichment

## Dashboard

::: musicseed_api.handlers.dashboard

## Jobs

::: musicseed_api.handlers.jobs

## Playlists

::: musicseed_api.handlers.playlists

## Sonic

::: musicseed_api.handlers.sonic
