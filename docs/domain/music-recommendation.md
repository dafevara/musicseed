# Music Recommendation Domain Notes

MusicSeed recommendations are built from signals already available in a personal Plex library plus
lightweight external enrichment.

## Core Entities

- Artist: performer or credited artist imported from Plex.
- Album: release container imported from Plex.
- Track: playable recording with metadata, file path, identifiers, tags, popularity,
  and Plex references.
- Mood, style, genre: Plex tag dimensions used as soft recommendation signals.
- Play history and track stats: listening behavior used for novelty and discovery.
- Playlist: selected recommendation output intended for Plex.

## Recommendation Signals

- Sonic similarity: cosine similarity between the seed profile's average Plex sonic vector and
  candidate vectors.
- Popularity proximity: closeness to the seed track popularity, not a generic popularity boost.
- Style alignment: overlap between seed and candidate styles.
- Genre alignment: overlap between seed and candidate genres.
- Era proximity: release year closeness.
- Novelty: favors less-played tracks using local play counts.

Mood was removed from scoring and candidate generation. Plex mood tags remain in the database and
are visible in `status`, but they introduce noise rather than a reliable ranking signal and have
been excluded from `SeedProfile`, `Weights`, `ScoreBreakdown`, and `build_candidate_pool()`.

Missing signals should degrade gracefully. A track without a popularity value or sonic vector
should not crash the recommendation flow; it should receive neutral or lower component scores
depending on the scoring function.

The per-track `ScoreBreakdown.availability` map distinguishes:

- `observed`: a real comparison (including genuine mid-range scores).
- `neutral_missing`: neutral `0.5` for missing/unusable sonic vectors or unknown popularity/year.
- `not_applicable`: the seed has no style/genre basis (score `0.5`).
- `missing`: the seed has tags but the candidate does not. **The historical Jaccard score remains
  zero**, but this is missing metadata, not evidence of a measured mismatch.
- `mixed`: frequency-populate votes used different availability states. Numeric scores remain
  the mean over the seeds that voted for the candidate, not all playlist seeds.
- `unknown`: a legacy score did not supply evidence metadata. No observed evidence is invented.

CLI `--explain` and web tooltips expose these distinctions. Zero-norm vectors were already neutral;
MUS-94 additionally treats non-finite or incompatible vectors as neutral rather than producing a
perfect NaN-derived similarity or an exception. This is an explicit invalid-input bug fix; valid
finite-input scoring, weights, and tag-missing numeric policy are unchanged.

## Popularity

Popularity is a supporting signal, not the main product. It should help distinguish candidates
inside the owner's collection, not turn recommendations into a global chart.

Preferred source order:

1. ListenBrainz recording popularity by MusicBrainz recording MBID.
2. Spotify popularity from matched tracks when ListenBrainz is unavailable or insufficient.

ListenBrainz raw counts are normalized into `Track.popularity_score` on a 0-1 scale. Spotify
popularity is a 0-100 provider value. Scoring converts the best available value to a comparable
0-100 scale before computing proximity to the seed profile.

## Sonic Vectors

Sonic similarity uses Plex's own sonic analysis vectors. Plex stores one 50-dimensional vector per
analyzed track in `com.plexapp.plugins.library.blobs.db`; MusicSeed copies them into its own
`track_vectors` table (`musicseed-cli import-plex-sonic`, or `POST /sonic/import` from the API),
then rebuilds an in-memory, L2-normalized matrix keyed by `plex_id` from that local store
(`core/src/musicseed/context.py`). Production scoring looks up these local vectors while streaming
all eligible scalar metadata; the older nearest-neighbor helper is retained for offline bounded
comparisons. No vector index is needed for the measured implementation; see the
[retrieval benchmark and limits](../resolvers/retrieval-decision.md), rather than assuming every
query is instantaneous. MusicSeed does not generate its own embeddings and never reads audio files.

Coverage is Plex's responsibility. A track Plex hasn't analyzed simply has no vector and receives
a neutral 0.5 sonic score. After vectors are imported, the recommender reads them from the local
`track_vectors` store and no longer needs the blobs database at query time. Check coverage with
`sonic-probe`; trigger analysis with `sonic-refresh`, then re-run `import-plex-sonic`.

Use sonic similarity as one signal among several. A recommendation should still produce reasonable
results for tracks without vectors by falling back to tags, era, popularity, and novelty.

## Diversity

Artist diversity is a selection constraint, not a score component. The current recommender limits
the number of selected tracks per artist after scoring. This makes the ranking easier to explain:
scores measure fit, constraints shape the final playlist.

## Matching Expectations

External catalog matching is inherently imperfect. Prefer precision over coverage for a personal
library:

- MBID-based ListenBrainz lookups are safer than text search.
- Spotify search matches should be conservative.
- Ambiguous seed text should ask the user to choose a more specific seed or use `--seed-id`.
- Avoid silently choosing among multiple plausible seed matches.

## Recommendation Quality Checks

When changing recommendation logic, inspect:

- Does `--explain` still make sense to a human?
- Are seed tracks excluded from candidates?
- Are all eligible non-seed tracks scored before the artist/limit constraints?
- Are missing metadata values handled without exceptions?
- Does artist diversity still apply after scoring?
- Do weights normalize correctly when users adjust them?
