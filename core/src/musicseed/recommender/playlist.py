"""Playlist recommendation orchestration."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal, Sequence

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from musicseed.db.models import Artist, Track
from musicseed.recommender.retrieval import (
    FEATURE_BATCH_SIZE,
    ConstrainedTopK,
    ScoredTrack,
    score_eligible_tracks,
)
from musicseed.recommender.scoring import (
    SIGNALS,
    ScoreBreakdown,
    SeedProfile,
    SignalStatus,
    SonicCoverage,
    Weights,
    build_seed_profile,
)
from musicseed.sonic import SonicVectors, get_sonic_vectors

RecommendMethod = Literal["average", "frequency"]
"""Seed aggregation strategies: ``"average"`` scores every eligible track
against the seeds' mean profile in one scan; ``"frequency"`` gathers per-seed
votes and ranks by their average score with vote count as a tiebreaker."""


def _average_score(scores: list[ScoreBreakdown]) -> ScoreBreakdown:
    if not scores:
        raise ValueError("Cannot average an empty set of scores")
    count = len(scores)
    availability: dict[str, SignalStatus] = {}
    for signal in SIGNALS:
        statuses = {score.availability.get(signal, "unknown") for score in scores}
        availability[signal] = next(iter(statuses)) if len(statuses) == 1 else "mixed"
    return ScoreBreakdown(
        total=sum(s.total for s in scores) / count,
        sonic=sum(s.sonic for s in scores) / count,
        popularity=sum(s.popularity for s in scores) / count,
        style=sum(s.style for s in scores) / count,
        genre=sum(s.genre for s in scores) / count,
        era=sum(s.era for s in scores) / count,
        novelty=sum(s.novelty for s in scores) / count,
        availability=availability,
    )


class Recommendation(BaseModel):
    """One recommended track with its score breakdown and candidate sources."""

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    track: Track
    score: ScoreBreakdown
    sources: list[str]


def _track_load_options():
    return (
        selectinload(Track.artist),
        selectinload(Track.album),
        selectinload(Track.moods),
        selectinload(Track.styles),
        selectinload(Track.genres),
        selectinload(Track.stats),
    )


def _format_track(track: Track) -> str:
    artist = track.artist.name if track.artist else "Unknown Artist"
    return f"{artist} - {track.title} (id={track.id})"


def _resolve_seed_text(session: Session, seed_text: str) -> Track:
    text = seed_text.strip()
    query = session.query(Track).options(*_track_load_options())

    if " - " in text:
        artist_text, title_text = [part.strip() for part in text.split(" - ", 1)]
        exact = (
            query.join(Artist, Track.artist_id == Artist.id)
            .filter(func.lower(Artist.name) == artist_text.lower())
            .filter(func.lower(Track.title) == title_text.lower())
            .first()
        )
        if exact:
            return exact

        matches = (
            query.join(Artist, Track.artist_id == Artist.id)
            .filter(Artist.name.ilike(f"%{artist_text}%"))
            .filter(Track.title.ilike(f"%{title_text}%"))
            .limit(6)
            .all()
        )
    else:
        exact = query.filter(func.lower(Track.title) == text.lower()).first()
        if exact:
            return exact
        matches = query.filter(Track.title.ilike(f"%{text}%")).limit(6).all()

    if not matches:
        raise ValueError(f"No seed track matched: {seed_text}")
    if len(matches) > 1:
        options = "; ".join(_format_track(track) for track in matches[:5])
        raise ValueError(f"Seed is ambiguous: {seed_text}. Matches: {options}")
    return matches[0]


def resolve_seed_tracks(
    session: Session,
    *,
    seed_texts: Sequence[str] | None = None,
    seed_ids: Sequence[int] | None = None,
) -> list[Track]:
    """Resolve seed IDs and seed text queries into loaded Track objects.

    Text seeds accept ``"Artist - Title"`` or a bare title; exact
    case-insensitive matches win, otherwise a substring search must narrow to
    exactly one track. Results are deduplicated, preserving input order.

    Args:
        session: open database session.
        seed_texts: seed tracks as text queries.
        seed_ids: seed tracks by local database id.

    Returns:
        The resolved seed tracks with artist, album, tags, and stats eagerly
        loaded.

    Raises:
        ValueError: when a seed id or text matches no track, a text seed is
            ambiguous (multiple matches), or no seeds were given at all.
    """
    seeds: list[Track] = []
    seen: set[int] = set()

    requested = list(dict.fromkeys(seed_ids or []))
    by_id: dict[int, Track] = {}
    for start in range(0, len(requested), FEATURE_BATCH_SIZE):
        by_id.update(
            (track.id, track)
            for track in session.query(Track)
            .options(*_track_load_options())
            .filter(Track.id.in_(requested[start : start + FEATURE_BATCH_SIZE]))
            .all()
        )
    for track_id in requested:
        track = by_id.get(track_id)
        if track is None:
            raise ValueError(f"No seed track found with id={track_id}")
        seeds.append(track)
        seen.add(track.id)

    for seed_text in seed_texts or []:
        track = _resolve_seed_text(session, seed_text)
        if track.id not in seen:
            seeds.append(track)
            seen.add(track.id)

    if not seeds:
        raise ValueError("At least one seed track is required")

    return seeds


def recommend_from_profile(
    session: Session,
    seed_profile: SeedProfile,
    vectors: SonicVectors,
    *,
    limit: int,
    weights: Weights,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    exclude_ids: set[int] | None = None,
) -> tuple[list[Recommendation], SonicCoverage]:
    """Score eligible scalar facts and materialize only the selected ORM tracks."""
    selected, coverage = score_eligible_tracks(
        session,
        seed_profile,
        vectors,
        limit=limit,
        weights=weights,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
        exclude_ids=exclude_ids,
    )
    ids = [record.id for record in selected]
    tracks: dict[int, Track] = {}
    for start in range(0, len(ids), FEATURE_BATCH_SIZE):
        tracks.update(
            (track.id, track)
            for track in session.query(Track)
            .options(*_track_load_options())
            .filter(Track.id.in_(ids[start : start + FEATURE_BATCH_SIZE]))
            .all()
        )
    return [
        Recommendation(track=tracks[r.id], score=r.score, sources=["eligible"]) for r in selected
    ], coverage


def recommend_frequency(
    session: Session,
    seed_tracks: list[Track],
    *,
    limit: int,
    per_seed_limit: int = 30,
    weights: Weights,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    vectors: SonicVectors,
    exclude_ids: set[int] | None = None,
) -> tuple[list[Recommendation], SonicCoverage]:
    """Recommend tracks voted for by multiple individual seed tracks.

    Each seed is used as its own single-track profile to score all eligible
    candidates; every seed (and any ``exclude_ids``) is excluded up front, and
    one vector-cache snapshot is reused across seeds. This costs one scalar
    scan per seed; prefer average mode for large seed sets. A candidate's
    score is the average of its per-seed scores across every seed that
    recommended it (its "votes"); results are ranked by that average score,
    with vote count as a tiebreaker, so ``limit`` cuts at the highest-scoring
    candidates. Each recommendation's ``sources`` lists the voting seed ids.

    Args:
        session: open database session.
        seed_tracks: resolved seed tracks, each used as an individual seed.
        limit: maximum number of recommendations to return.
        per_seed_limit: candidates gathered per seed.
        weights: signal weights.
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap applied during selection.
        min_score: drop recommendations with a total score below this value.
        vectors: Plex sonic vectors to score against.
        exclude_ids: additional track ids to exclude before per-seed budgets;
            seed track ids are always excluded.

    Returns:
        Aggregated recommendations, best first, and the sonic coverage of the
        candidate pool (identical for every per-seed scan).
    """
    if per_seed_limit <= 0:
        raise ValueError("per_seed_limit must be greater than zero")
    if not seed_tracks:
        return [], SonicCoverage(candidates=0, with_vector=0)
    excluded = set(exclude_ids or set()) | {track.id for track in seed_tracks}
    selected = ConstrainedTopK(limit, max_tracks_per_artist)
    votes: dict[int, list[tuple[int, ScoreBreakdown, Track]]] = defaultdict(list)
    coverage = SonicCoverage(candidates=0, with_vector=0)

    for seed_track in seed_tracks:
        recs, seed_coverage = recommend_from_profile(
            session,
            build_seed_profile([seed_track], vectors),
            vectors,
            limit=per_seed_limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=max_tracks_per_artist,
            exclude_ids=excluded,
        )
        coverage = SonicCoverage(
            candidates=max(coverage.candidates, seed_coverage.candidates),
            with_vector=max(coverage.with_vector, seed_coverage.with_vector),
        )
        for rec in recs:
            votes[rec.track.id].append((seed_track.id, rec.score, rec.track))

    for track_id, entries in votes.items():
        score = _average_score([score for _, score, _ in entries])
        if min_score is None or score.total >= min_score:
            selected.add(ScoredTrack(track_id, entries[0][2].artist_id, score, len(entries)))
    return [
        Recommendation(
            track=votes[record.id][0][2],
            score=record.score,
            sources=[str(seed_id) for seed_id, _, _ in votes[record.id]],
        )
        for record in selected.results()
    ], coverage


def recommend_tracks(
    session: Session,
    *,
    seed_texts: Sequence[str] | None = None,
    seed_ids: Sequence[int] | None = None,
    limit: int = 50,
    method: RecommendMethod = "average",
    per_seed_limit: int = 30,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
    vectors: SonicVectors | None = None,
) -> tuple[list[Track], list[Recommendation], SonicCoverage]:
    """Score every eligible non-seed track and return the exact constrained top-k.

    Resolve seeds, filter years, stream scalar scoring facts, and retain the
    best ``limit`` under the artist cap and score threshold. ``method="average"``
    (the default) aggregates the seeds into one mean profile and scores in a
    single scan; ``method="frequency"`` scores each seed individually and ranks
    by per-seed vote average with vote count as a tiebreaker. This is
    equivalent to globally sorting by score then local ID, but loads ORM graphs
    only for seeds and selected tracks. No source budget can omit an eligible
    candidate. Average-populate uses this same pipeline.

    Args:
        session: open database session.
        seed_texts: seed tracks as text queries (see ``resolve_seed_tracks``).
        seed_ids: seed tracks by local database id.
        limit: maximum number of recommendations to select.
        method: ``"average"`` or ``"frequency"`` (see ``RecommendMethod``).
        per_seed_limit: candidates gathered per seed ("frequency" method only).
        weights: signal weights; defaults to ``Weights()``.
        year_min: only recommend tracks released in this year or later.
        year_max: only recommend tracks released in this year or earlier.
        max_tracks_per_artist: artist diversity cap applied during selection.
        min_score: drop recommendations with a total score below this value.
        vectors: Plex sonic vectors to score against; defaults to the default
            context's cached vectors.

    Returns:
        ``(seed_tracks, selected, sonic_coverage)`` where ``sonic_coverage``
        reports how many candidate tracks had a real Plex sonic vector.

    Raises:
        ValueError: if ``limit`` or ``max_tracks_per_artist`` is not positive,
            if ``method`` is unknown, if ``per_seed_limit`` is not positive in
            frequency mode, or if the seeds cannot be resolved.
    """
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    if max_tracks_per_artist <= 0:
        raise ValueError("max_tracks_per_artist must be greater than zero")

    weights = weights or Weights()
    if vectors is None:
        vectors = get_sonic_vectors()
    seed_tracks = resolve_seed_tracks(session, seed_texts=seed_texts, seed_ids=seed_ids)
    if method == "frequency":
        selected, coverage = recommend_frequency(
            session,
            seed_tracks,
            limit=limit,
            per_seed_limit=per_seed_limit,
            weights=weights,
            year_min=year_min,
            year_max=year_max,
            max_tracks_per_artist=max_tracks_per_artist,
            min_score=min_score,
            vectors=vectors,
        )
        return seed_tracks, selected, coverage
    if method != "average":
        raise ValueError(f"Unknown recommendation method: {method}")
    seed_profile = build_seed_profile(seed_tracks, vectors)
    selected, coverage = recommend_from_profile(
        session,
        seed_profile,
        vectors,
        limit=limit,
        weights=weights,
        year_min=year_min,
        year_max=year_max,
        max_tracks_per_artist=max_tracks_per_artist,
        min_score=min_score,
    )
    return seed_tracks, selected, coverage
