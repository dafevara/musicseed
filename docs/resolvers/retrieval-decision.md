# Retrieval and schema decisions (MUS-96)

## Decision: score every eligible track

Use **one exact scalar-streaming pipeline** for ordinary recommendations and populate-average.
There is no size-dependent fallback or user-facing shortlist mode. The original bounded retriever
remains only as an explicitly named offline reference, so its known omissions remain measurable.

The MUS-95 fixtures exposed two concrete losses: seeds exhausted a source budget (0 results when
5 were feasible), and unordered tag limits omitted a perfect style match. Those are retrieval
errors relative to the existing scoring objective, not a reason to introduce another signal.

`score_eligible_tracks()` reads only scoring columns, stats and tag names in 500-row batches.
Year eligibility is applied in SQL. All seed/excluded IDs are removed before tags, scores and
selection budgets. There is no per-source truncation. `score_signals()` is shared with the ORM
`calculate_score()` adapter, including the same missing-data evidence and popularity precedence.

`ConstrainedTopK` retains at most the requested count. When an artist group is full, a better
candidate replaces that group's worst; otherwise it can replace the global worst. This gives the
same answer as globally sorting then applying the artist cap, without retaining every scored
track. Stale heap keys are bounded too. Unknown artists share one cap group, as before.
Only seeds and final selected tracks load ORM relationships, and services still project their
DTOs inside the session. Large seed-ID lookups and selected-track hydration use bounded SQL lists.

### Observable behavior

- Results sort by **score descending, then local ID ascending**. Frequency adds descending vote
  count before the ID tiebreaker.
- `min_score` rejects individual scalar rows before selection; unlike the old sorted-list loop,
  it cannot stop the ID-ordered scan at the first low score.
- Recommendation/average sources now say `eligible`, meaning full eligible-library retrieval,
  not that every signal was observed. Per-component availability remains the evidence source.
- Sonic coverage counts **all eligible non-seed candidates before score/artist constraints**,
  not the historical shortlist. A usable candidate vector does not imply a usable seed profile.
- Frequency resolves distinct seeds once, excludes the complete playlist before every per-seed
  vote budget, and reuses one vector-cache snapshot. Duplicate seed IDs produce one vote each.
  Scores are still averaged over voting seeds only; frequency sources still contain those IDs.
- For the same candidate/profile, component formulas, weights, normalization and valid-input
  numeric scores are unchanged. Selections can change because retrieval is complete, ties are
  explicit, and playlist seeds no longer consume vote budgets. Frequency totals can also change
  when different seeds vote; averaging arithmetic is unchanged. Approved preview IDs are still
  applied without recomputation.

## Reproduce the evidence

From the monorepo root:

```bash
cd core
uv run --no-sync python ../scripts/evaluate_recommendations.py --output /tmp/evaluation.json
uv run --no-sync python ../scripts/benchmark_retrieval.py --sizes 1000 10000 50000 100000 --repeats 3 --output /tmp/retrieval.json
uv run --no-sync python ../scripts/benchmark_retrieval.py --sizes 50000 --repeats 3 --no-extra-indexes --output /tmp/retrieval-no-indexes.json
uv run --no-sync python ../scripts/benchmark_retrieval.py --sizes 50000 --repeats 3 --year-window 2000 2005 --output /tmp/retrieval-narrow.json
```

These developer commands use only generated temporary databases and vectors. They do not import
or export the owner's library, load the owner's configuration, contact Plex/providers, or run
jobs against a NAS. `--output` replaces only the explicitly named report file.

Committed evidence:

- [Original MUS-95 fixture report](../evaluation/bounded-v1-seed7.json).
- [Full-scoring fixture report](../evaluation/full-v1-seed7.json).
- [1k/10k/50k/100k benchmark](../evaluation/retrieval-v1-seed7.json).
- [50k with initialization-only indexes](../evaluation/retrieval-no-indexes-v1-seed7.json).
- [50k with a narrow year window](../evaluation/retrieval-narrow-v1-seed7.json).

The full fixture output matches the exhaustive current-score oracle, including the previously
omitted perfect style match and the large-seed fill. The bounded reference still exposes its
losses. This is a correctness comparison against the current objective, **not a listening result**.

### Recorded results

Seed 7, two seeds, limit 50, artist cap 3; Linux/aarch64, Python 3.14.7, NumPy 2.5.0.
Times below are warm medians; memory is the separate traced request peak, **not total RSS**.

| Library tracks | Bounded time | Full time | Bounded oracle candidate recall | Bounded / full traced MiB |
|---:|---:|---:|---:|---:|
| 1,000 | 0.056 s | 0.042 s | 100% | 5.89 / 1.00 |
| 10,000 | 0.096 s | 0.351 s | 54% | 10.21 / 1.49 |
| 50,000 | 0.121 s | 1.726 s | 14% | 11.32 / 1.84 |
| 100,000 | 0.141 s | 3.449 s | 8% | 11.55 / 1.93 |

The full pass materialized 52 ORM tracks (two seeds plus 50 selections) at every size. This is a
**latency-for-completeness trade-off** at larger sizes, not a claim that full scoring is faster.
The measured warm preview cost is practical for this local tool; no approximate fallback is needed.

At 50k, initialization-only indexes gave the same selected IDs and a 1.724 s full median versus
1.726 s with optional indexes—indistinguishable for this wide-window test, not proof that indexes
are unnecessary for every query. The indexed 2000–2005 window had 6,060 eligible tracks and a
0.211 s full median. Raw samples, memory scopes and controls are in the linked JSON reports.

### Timing and memory methodology

The benchmark records seed, recipe version, sizes, default `Weights()` values, year controls,
interpreter/NumPy/SQLite versions, architecture and CPU count. Fixtures include clustered 50-D
vectors, missing metadata/vectors, tags, stats, artist/album relationships and unused wide Track
metadata. They are synthetic, not a representative export of any particular owner library.

Each size/strategy gets a fresh worker. BLAS/OpenMP thread environment variables are set to one;
workers are not pinned to a core and the host is not guaranteed otherwise idle. Fixture creation,
index creation and vector-cache preparation are excluded. The first request is recorded but is
**not OS-cold**. Three further requests use new sessions and contribute their raw times/median.
This measures seed resolution, retrieval, scoring, selection and selected ORM hydration—not
cold JSON-vector decoding, API transport, browser rendering, imports, or Plex operations.

RSS is a high-water measurement including the interpreter, cache and query allocations, not a
request delta. Linux uses `/proc/self/status` `VmHWM` to avoid `getrusage` retaining a parent's
pre-exec footprint; macOS uses process `ru_maxrss`, which can include launch footprint. RSS is
recorded before a separate, untimed `tracemalloc` pass. That pass measures traced request
allocations, not every native allocation and not the already-resident vector cache. SQL and ORM
object counts are also recorded. Do not equate a small traced peak with total process memory.

The selector retains O(limit) scores, plus a scalar/tag batch. The existing cache retains raw and
normalized vector matrices and ID mappings; seed ORM metadata is also retained. Scoring CPU work
scales with eligible tracks and vector dimension. A wider library still costs a full scalar scan;
without a year index, finding a narrow window also requires SQLite to inspect the wider table.

**Limits:** timings are measurements on the recorded synthetic host, not an SLA or proof for all
real libraries. Frequency performs one full pass per distinct seed and can be expensive for large
playlists: prefer the default average mode there. No large-playlist frequency latency guarantee,
cold-start guarantee, or musical-superiority claim is made. Re-measure an owner's workload before
adding caching, vector indexes, or an approximate strategy.

## Schema/refactoring decisions

| Proposal | Decision now | Evidence and revisit trigger |
|---|---|---|
| Compact reads and a shared scorer | **Adopt** | Exact fixture parity and measured request allocation/ORM counts avoid full candidate graphs without changing the scoring objective. |
| MUS-80: provider enrichment table | **Keep current columns; defer migration** | Projection avoids materializing unused provider facts for every candidate. No provider-write/freshness bottleneck was measured here. Revisit for new providers or explicit per-provider freshness/history requirements, with preservation/resume tests. |
| MUS-81: schema versions | **Keep additive compatibility; defer version ledger** | This change requires no new tables/columns. Existing `ensure_schema()` behavior remains; `PRAGMA user_version` was not introduced. Before a nontrivial schema evolution, define baseline upgrade fixtures and a small ordered version plan. |
| MUS-81: indexes during initialization | **Keep explicit optimization for now** | Primary/unique indexes support the scalar/tag/stats reads. The benchmark includes both optimized and initialization-only databases; it does not implement the backlog's init/index contract. `optimize-db` remains the explicit additional-index operation. |
| MUS-82: docs drift sensors | **Adopt focused checks; defer the general sweep** | Actual Typer options validate recommendation examples; developer-script help, score defaults, and changed diagram/symbol references have focused checks. General API/web/README table reconciliation is not claimed. |
| MUS-83 accepted `sonic_version` gap | **Defer semantic vector versioning** | The current 50-D format is unchanged. `runtime_state.sonic_generation` is a cache-mutation revision, not a schema version or sonic model version. Revisit when vector format/meaning changes. |

Popularity remains normalized-value-first, with raw Spotify fallback only when the normalized
value is absent, on the existing 0–100 scale. Enrichment writes, provider precedence, resume and
missing-only behavior are not rewritten. Provider-specific freshness explanations remain outside
this change. No migration framework, enrichment table, queue, vector database, or frontend rewrite
was added. Related MUS-75/80/81/82 are not automatically closed by this decision.

See the [evaluation guide](recommendation-evaluation.md) for the owner listening protocol.
**Listening preference remains unmeasured.**
