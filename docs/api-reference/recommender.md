# Recommender

Recommendation engine internals from `musicseed-core` (`musicseed.recommender.*`). Production
retrieval scores all eligible non-seed tracks in scalar SQL batches and retains an exact,
artist-constrained top-k. Only seeds and selected tracks load ORM graphs. Average uses one
library scan; frequency uses one per distinct seed and ranks mean scores, then votes, then IDs.

See [recommendation resolvers](../resolvers/recommendation-resolvers.md) for the full flow and
[retrieval decisions](../resolvers/retrieval-decision.md) for measurements and limits.

## Scoring

::: musicseed.recommender.scoring

## Eligible retrieval and constrained selection

::: musicseed.recommender.retrieval

## Playlist

::: musicseed.recommender.playlist

## Populate

::: musicseed.recommender.populate

## Historical candidate pool

`build_candidate_pool` is retained for offline baseline comparisons. It is not used as the
production retrieval path or as a fallback.

::: musicseed.recommender.candidates
