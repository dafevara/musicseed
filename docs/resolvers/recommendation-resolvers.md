# Recommendation Resolvers

This document explains how seed input becomes a ranked recommendation list.

## Entry Points

- CLI command: `musicseed recommend` in `src/musicseed/cli.py`.
- Orchestration: `src/musicseed/recommender/playlist.py`.
- Candidate generation: `src/musicseed/recommender/candidates.py`.
- Scoring: `src/musicseed/recommender/scoring.py`.

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
- Average embedding when seed embeddings exist.
- Union of seed moods, styles, and genres.
- Average seed year.
- Average seed popularity on a 0-100 scale.

Multiple seeds should represent a shared target vibe. If a change makes multi-seed behavior less
predictable, update this doc and the `--explain` output.

## Candidate Pool

`build_candidate_pool()` gathers overlapping candidate IDs from available signals:

- Sonic neighbors from pgvector.
- Tracks sharing seed genres.
- Tracks sharing seed moods.
- Tracks sharing seed styles.
- Tracks near the seed era.
- Tracks near seed popularity.
- Low-play-count tracks for novelty.

The candidate pool is intentionally larger than the requested playlist length, allowing scoring
and artist diversity constraints to shape the final result.

## Scoring

`calculate_score()` computes component scores and a weighted total:

- `sonic`: cosine similarity normalized to 0-1.
- `popularity`: proximity to seed popularity.
- `mood`: Jaccard overlap.
- `style`: Jaccard overlap.
- `genre`: Jaccard overlap.
- `era`: proximity within a 50-year window.
- `novelty`: inverse function of play count.

Default weights live in `Weights` and mirror `RecommendationWeights` in config:

```text
sonic=0.30
popularity=0.15
mood=0.15
style=0.10
genre=0.15
era=0.05
novelty=0.10
```

Weights are normalized by their sum at scoring time.

## Selection

After scoring:

1. Seed tracks are excluded.
2. Candidates are sorted by total score descending.
3. `max_tracks_per_artist` is applied as a final diversity constraint.
4. The top `limit` selected recommendations are returned.

Artist diversity should remain a final constraint unless there is a clear reason to make it part
of scoring.

## Explainability

`--explain` should expose enough detail to answer:

- Which sources produced this candidate?
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
- Use a dry run: `uv run musicseed recommend --seed-id 123 --limit 20 --dry-run --explain`.
- Confirm missing embeddings, missing popularity, and missing tags do not crash scoring.
- Confirm ambiguous seed text still fails clearly.
