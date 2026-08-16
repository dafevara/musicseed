# MusicSeed Docs

MusicSeed is a personal, local-first music recommendation tool for a Plex library. It generates
Plex playlists from seed tracks using local library metadata, popularity enrichment, Plex sonic
analysis vectors (read at query time), and play history.

## Where to start

- [Product overview](product/overview.md) — product intent and scope.
- [Music recommendation domain](domain/music-recommendation.md) — domain concepts.
- [Recommendation resolvers](resolvers/recommendation-resolvers.md) — seed matching, candidate
  generation, scoring, and playlist selection.
- [Local runtime](infra/local-runtime.md) — local services, config, logs, and verification.
- [Troubleshooting](infra/troubleshooting.md) — setup and job failure recovery.
- [Harness engineering](harness-engineering.md) — harness strategy and maintenance loop.
- [API Reference](api-reference/core-services.md) — auto-generated Python API docs for the core
  services, the recommender, and the API handlers.

The visual dependency/workflow explainer lives at
[musicseed-dependency-architecture.html](musicseed-dependency-architecture.html) (raw HTML).
