# Music Recommendation Domain Notes

MusicSeed recommendations are built from signals already available in a personal Plex library plus
lightweight external enrichment.

## Core Entities

- Artist: performer or credited artist imported from Plex.
- Album: release container imported from Plex.
- Track: playable recording with metadata, file path, identifiers, tags, popularity, embedding,
  and Plex references.
- Mood, style, genre: Plex tag dimensions used as soft recommendation signals.
- Play history and track stats: listening behavior used for novelty and discovery.
- Playlist: selected recommendation output intended for Plex.

## Recommendation Signals

- Sonic similarity: vector similarity between the seed embedding profile and candidate embeddings.
- Popularity proximity: closeness to the seed track popularity, not a generic popularity boost.
- Mood alignment: overlap between seed and candidate moods.
- Style alignment: overlap between seed and candidate styles.
- Genre alignment: overlap between seed and candidate genres.
- Era proximity: release year closeness.
- Novelty: favors less-played tracks using local play counts.

Missing signals should degrade gracefully. A track without a popularity value or embedding should
not crash the recommendation flow; it should receive neutral or lower component scores depending
on the scoring function.

## Popularity

Popularity is a supporting signal, not the main product. It should help distinguish candidates
inside the owner's collection, not turn recommendations into a global chart.

Preferred source order:

1. ListenBrainz recording popularity by MusicBrainz recording MBID.
2. Spotify popularity from matched tracks when ListenBrainz is unavailable or insufficient.

ListenBrainz raw counts are normalized into `Track.popularity_score` on a 0-1 scale. Spotify
popularity is a 0-100 provider value. Scoring converts the best available value to a comparable
0-100 scale before computing proximity to the seed profile.

## Embeddings

Embeddings represent audio similarity and are stored in pgvector as 512-dimensional vectors.
Generation is expensive compared with metadata operations, so development runs should use
`--limit`, `--workers 1`, and `--missing-only`.

Use embeddings as one signal among several. A recommendation should still produce reasonable
results when embeddings are incomplete by falling back to tags, era, popularity, and novelty.

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
- Does the candidate pool include more tracks than the requested playlist length?
- Are missing metadata values handled without exceptions?
- Does artist diversity still apply after scoring?
- Do weights normalize correctly when users adjust them?
