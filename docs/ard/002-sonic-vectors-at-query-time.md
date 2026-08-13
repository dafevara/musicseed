# ARD 002 — Plex Sonic Vectors at Query Time, No Self-Embeddings

**Status:** Accepted (implemented)
**Date:** July 2026
**Supersedes:** parts of [ARD 001](001-initial-system-design.md) — see "Superseded sections" below

---

## Decision

MusicSeed no longer generates its own audio embeddings and no longer stores any vectors in its
own database.

- The Essentia/MusiCNN self-embedding pipeline is removed: `core/src/musicseed/embeddings/`, the
  `embed` CLI command, `EmbeddingConfig`, and the `essentia-tensorflow` dependency.
- The `tracks.embedding` / `embedding_model` / `embedding_generated` columns, the `pgvector`
  dependency, and the IVFFlat index are removed.
- The only sonic signal is Plex's own sonic analysis: 50-dimensional vectors stored by Plex in
  `com.plexapp.plugins.library.blobs.db`, read **at query time** by
  `core/src/musicseed/sonic.py` into an in-memory, L2-normalized matrix keyed by `plex_id`.
  Nearest-neighbor search is a single numpy matmul; scoring looks vectors up by `plex_id`.
- The `import-plex-sonic` command and service are removed: there is no copy to import, so nothing
  can drift out of date.

## Rationale

- Self-generated embeddings were an experiment that lost to Plex's vectors. Keeping two vector
  sources forced the 50→200 zero-padding hack and the `embedding_model` comparability guard.
- ~60K tracks × 50 float32 dims ≈ 12 MB: brute-force cosine search is single-digit milliseconds,
  faster than a round-trip to a Postgres server. pgvector was load-bearing only for the sonic
  candidate query; scoring-side cosine similarity was already pure numpy.
- Dropping `embed` deletes all audio-file access. MusicSeed now only reads Plex's two SQLite
  databases (metadata + blobs), the Plex HTTP API, and external metadata APIs.

## Consequences

- `recommend` requires the Plex blobs database and fails with `NotFoundError` if it is
  unavailable. Per-track missing vectors still degrade to a neutral 0.5 sonic score.
- Sonic coverage is Plex's responsibility: `sonic-probe` reports it, `sonic-refresh` triggers
  Plex's MusicAnalysis Butler task.
- `status` reports "Plex sonic" coverage by intersecting the in-memory vector set with imported
  tracks instead of counting stored embeddings.
- Shipped in the same change: track years fall back to the album year during import (Plex rarely
  sets year on track rows), improving the era signal.

## Superseded sections of ARD 001

- §4–§5 architecture and data-flow diagrams (Embedding Generator component, Step 3 embedding
  flow, pgvector candidate retrieval)
- §7 database schema (`embedding`, `embedding_model`, `embedding_generated` columns; IVFFlat
  index)
- §9 recommendation algorithm details that reference stored embeddings / pgvector
- §11 tech stack (Essentia and pgvector rows; §11.4 embedding model table)
- §12 configuration (`embedding:` section)
- §13 Phase 3 (Embeddings)

The PostgreSQL → SQLite migration has since shipped: MusicSeed now uses a single local SQLite
file (see [`docs/musicseed-dependency-architecture.html`](../musicseed-dependency-architecture.html));
ARD 001's PostgreSQL-specific database sections no longer apply.
