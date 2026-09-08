# Recommendation Resolvers

This document explains how seed input becomes a ranked recommendation list.

## Entry Points

- CLI command: `musicseed-cli recommend` in `cli/src/musicseed_cli/commands/recommend.py`.
- Orchestration: `core/src/musicseed/recommender/playlist.py`.
- Eligible scoring/selection: `core/src/musicseed/recommender/retrieval.py`.
- Historical bounded reference (offline comparisons only): `core/src/musicseed/recommender/candidates.py`.
- Scoring: `core/src/musicseed/recommender/scoring.py`.
- Sonic vectors (read from the local `track_vectors` store): `core/src/musicseed/sonic.py`.

## Seed Resolution

Seeds can be provided as database IDs or text.

- `--seed-id` resolves directly by `Track.id`.
- `--seed "Artist - Title"` first attempts exact lowercase artist and title matching.
- Text without `Artist - Title` matches by title.
- Ambiguous text matches raise an error and include candidate IDs.

This is intentional. For a personal music library, choosing the wrong seed silently is worse than
asking the user for a better seed.

## Seed Profile

Resolved seed tracks are combined into a `SeedProfile`:

- Track IDs to exclude from recommendations.
- Average of the seeds' Plex sonic vectors (looked up by `plex_id`); absent when no seed has one.
- Union of seed styles and genres.
- Average seed year.
- Average seed popularity on a 0-100 scale.

Multiple seeds should represent a shared target vibe. If a change makes multi-seed behavior less
predictable, update this doc and the `--explain` output.

## Eligible Library

`score_eligible_tracks()` scores every eligible non-seed track using scalar SQL batches rather
than a bounded source shortlist. Years are filtered before scoring; all seed/excluded IDs are
removed before tags, scoring and selection budgets. Only seeds and selected tracks load ORM
relationships. `recommend_from_profile()` is shared by normal and playlist recommendation flows.

The historical `build_candidate_pool()` remains an offline diagnostic reference, not a production
fallback. Its source limits can miss a perfect style match or consume a budget with seeds.
See [the measured retrieval decision](retrieval-decision.md) for benchmarks, memory bounds,
frequency-mode limits and explicit schema/enrichment decisions.

For deterministic offline comparisons, known retrieval gaps, and an owner listening protocol,
see [recommendation evaluation](recommendation-evaluation.md). Synthetic results do not establish
musical preference.

## Scoring

`score_signals()` computes component scores and a weighted total; `calculate_score()` is the
ORM adapter to the same function:

- `sonic`: cosine similarity normalized to 0-1.
- `popularity`: proximity to seed popularity.
- `style`: Jaccard overlap.
- `genre`: Jaccard overlap.
- `era`: proximity within a 50-year window.
- `novelty`: inverse function of play count.

Missing sonic/popularity/year uses neutral `0.5`. Missing seed tags also use `0.5`; missing
candidate tags with a tagged seed retain the historical **zero** score, labelled `missing` rather
than observed. `ScoreBreakdown.availability` distinguishes `observed`, `neutral_missing`,
`not_applicable`, `missing`, `mixed`, and legacy `unknown` evidence. Frequency-populate preserves
uniform statuses and marks differing vote statuses `mixed`, without changing numeric averaging.
CLI `--explain` and web tooltips surface all these states; see
[the domain guide](../domain/music-recommendation.md) for the invalid-vector bug-fix boundary.

Default weights live in `Weights` and mirror `RecommendationWeights` in config:

```text
sonic=0.30
popularity=0.15
style=0.10
genre=0.15
era=0.05
novelty=0.10
```

Weights are normalized by their sum at scoring time, so removing a signal shifts relative weight
to the remaining signals proportionally — no manual rebalancing needed.

Mood was removed from scoring because it introduced noise for this library. Plex mood tags are
still stored and visible in `status`, but excluded from `Weights`, `ScoreBreakdown`, `SeedProfile`,
and `build_candidate_pool()`.

## Service and approval boundaries

Recommendation/populate services map ORM tracks to JSON-safe DTOs while sessions are open.
Artist, album, year, popularity, local/Plex IDs, scores, sources and normal recommendation coverage
remain serializable after session closure and engine disposal. Only internal recommendation
objects carry ORM tracks.

A preview followed by confirmation is **not** a second recommendation request. CLI/web creation
writes the preview's seed IDs plus its approved recommendation IDs in order; populate writes the
approved IDs (including any user pruning). Empty or malformed API selections fail. Stale local
IDs or tracks without a Plex mapping reject the whole write before any Plex mutation, rather than
silently writing a subset. Duplicate IDs are collapsed in first-occurrence order.

The API's create and populate write routes now require `track_ids`; seed-only/selection-free
clients must preview first. Core retains explicit generate-and-write entry points for callers
that intentionally do not implement a preview workflow.

## Selection

After scoring:

1. Seed tracks and out-of-window years have already been excluded.
2. `min_score` rejects individual low-score rows; it does not stop the ID-ordered scalar scan.
3. `ConstrainedTopK` retains the exact top `limit` under `max_tracks_per_artist`, replacing the
   relevant worst selection when a better candidate arrives. This is equivalent to globally
   sorting then applying the artist cap, but retains only O(limit) scores.
4. Results are returned by total score descending, then local ID ascending. Frequency adds vote
   count descending before the ID tiebreaker; it excludes the entire playlist before each
   per-seed budget and counts distinct seeds only.
5. Only the selected tracks are materialized for DTO projection inside the service session.

`min_score` defaults to `None` (no cutoff). When supplied via `--min-score`, it must be in
`[0.0, 1.0]`. The result may contain fewer than `limit` tracks when the threshold is active.

Artist diversity should remain a final constraint unless there is a clear reason to make it part
of scoring.

## Explainability

`--explain` should expose enough detail to answer:

- Which retrieval path produced this candidate? Normal/average sources now say `eligible`;
  frequency sources are voting seed IDs, not invented signal observations.
- Which score components were strong or weak?
- Did a selection constraint affect the final playlist?

When adding a signal, update:

- Candidate source labels.
- `ScoreBreakdown`.
- CLI explain output.
- This document.

## Safe Change Checklist

- Run `python3 -m compileall -q src/musicseed`.
- Run `uv run ruff check src` if dependencies are available.
- Use the read-only preview: `musicseed-cli recommend --seed-id 123 --limit 20 --explain`.
  `recommend` never writes playlists and has no `--dry-run` flag.
- Confirm tracks without sonic vectors, missing popularity, and missing tags do not crash scoring.
- Confirm recommendations still work without Plex source databases/network after local vector import.
  Missing local vectors use neutral sonic scores; source databases are import-time dependencies.
- Confirm ambiguous seed text still fails clearly.
