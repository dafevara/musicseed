# API Handlers

Surface-agnostic orchestration from `musicseed-api` (`musicseed_api.handlers.*`). Handlers call
core services, manipulate config, manage job lifecycles, and map errors; routes stay thin.

The HTTP contract itself is the FastAPI OpenAPI schema served at `/openapi.json`; `api/routes/*`
is intentionally not documented here.

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
