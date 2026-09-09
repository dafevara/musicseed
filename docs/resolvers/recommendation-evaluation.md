# Offline recommendation evaluation

This developer harness evaluates **synthetic fixtures**, not the owner's music taste or real
library. It neither loads the user's configuration/database nor contacts Plex or providers.
Every run creates small SQLite databases in an automatically cleaned temporary directory.

## Run

From the monorepo root:

```bash
cd core
uv run --no-sync python ../scripts/evaluate_recommendations.py
uv run --no-sync python ../scripts/evaluate_recommendations.py --case perfect_style --case large_seed_set
uv run --no-sync python ../scripts/evaluate_recommendations.py --seed 7 --output /tmp/musicseed-evaluation.json
```

Default output is JSON on stdout. `--output` replaces only the explicitly named report file.
The command exits nonzero for a safety-invariant violation (duplicates, seed/year/artist/threshold
violations, non-finite scores, or exceeding the requested count). Ranking differences, low recall,
and legitimate underfill are reported, **not hidden by turning them into passing quality scores**.
They do not make the command fail. MUS-95 established the historical baseline; MUS-96 now uses
full eligible scoring, while retaining the old bounded retriever as a diagnostic reference.

Reports record fixture version, RNG seed, per-case request controls and a SHA-256 fingerprint of
all synthetic facts/parameters. They omit timestamps, elapsed times, temporary paths, and private
identifiers. With the same code/dependency versions, repeated runs produce identical JSON; native
mean scores are rounded to 12 decimal places. Do not compare reports with different fixture
fingerprints as though the input library were unchanged.

## Comparators

Each fixture runs three strategies under the same seed/year/artist/limit constraints:

1. **`current`**: the production recommendation/populate pipeline and the case's weights.
2. **`exhaustive_oracle`**: the same profiles, component scorer and frequency averaging, but every
   eligible non-seed track is scored before selection. A small independent greedy selector uses
   score, vote count where relevant, then local ID as its deterministic tiebreakers.
3. **`sonic_novelty_baseline`**: exhaustive scoring using 80% sonic similarity and 20% novelty, with
   the same eligibility/diversity constraints. These heuristic weights are a simple comparison,
   not fitted or validated listening preferences.

The oracle isolates retrieval/selection loss; it **shares the production scorer** and is not an
independent proof that scoring is correct. Numerical unit tests check the underlying cosine,
Jaccard, proximity, novelty, and normalization formulas separately. Native score means from
strategies with different weights are not comparable quality ratings.

Frequency oracle/baseline runs exclude the entire playlist before each per-seed vote budget,
then aggregate scores over voting seeds only. Candidate recall is a separate diagnostic of the
original bounded multi-source retriever: for frequency it uses the union of per-seed pools, not
recall of every individual vote. This reference remains useful when evaluating a different
production retrieval policy.

## Fixtures and metrics

| Case | What it checks |
|---|---|
| `dense` | Complete synthetic metadata with six vector clusters; constrained selection |
| `sparse` | Absent tags/year/popularity, missing/zero vectors, explicit fallback evidence |
| `narrow_era` | Global nearest neighbors outside the requested year window |
| `large_seed_set` | Seeds consuming a bounded source budget before exclusion |
| `perfect_style` | A perfect style match beyond unordered tag/novelty limits |
| `artist_capacity` | Legitimate underfill because too few artist groups can pass the cap |
| `empty_window` | No eligible release years; an empty recommendation is correct |
| `populate_average` | Aggregated playlist seeds and a score threshold |
| `populate_frequency` | Per-seed votes, partial evidence, and final diversity constraints |

Per-strategy results include selected IDs, fill, unique known artists, duplicate/seed/year/artist/
threshold violations, non-finite score counts, per-signal availability counts, and top-k overlap
with the current-score oracle. A separate bounded-pool probe reports candidate count, missing
oracle IDs, and oracle top-k recall. Recall/overlap is `null` when the oracle is empty, rather than
inventing a perfect score. Underfill is compared with oracle fill so infeasible requests are not
confused with retrieval starvation.

The [MUS-95 bounded baseline report](../evaluation/bounded-v1-seed7.json) captures fixture version 1,
seed 7, before retrieval simplification. Its known style/large-seed gaps are deliberately visible;
passing safety invariants must not be interpreted as proving complete retrieval. Compare it with
the [full-scoring report](../evaluation/full-v1-seed7.json), whose production results match the
current-score oracle in these fixtures. See the [retrieval decision](retrieval-decision.md) for
performance methodology, measured trade-offs and remaining limits.

## Owner listening review (not yet performed)

Synthetic consistency is not musical effectiveness. For an optional owner review:

1. Choose 5–10 familiar seeds/playlists spanning dense and sparse metadata, a narrow era, and a
   larger playlist. Record the seed selection, weights, limits and library snapshot privately.
2. Generate production and simple-baseline previews without writing playlists. Randomize their
   labels and review the same number of tracks under the same year/artist constraints.
3. For each preview, rate fit to the seed, unwanted repeats, discovery value and willingness to
   keep listening. Note disliked transitions and missing/unrecognized tracks separately.
4. Record per-seed preferences, ties and reasons. Repeat on another day and keep some seeds out
   of any tuning round. Do not tune and evaluate on exactly the same short list.
5. Only create Plex playlists after approving the exact displayed IDs. Keep notes and any real
   library data local; do not publish listening history or private library exports.

The shipped report explicitly says `listening_preference: "unmeasured"`. Neither this fixture
suite, a higher native score, nor a faster synthetic benchmark establishes musical superiority.
