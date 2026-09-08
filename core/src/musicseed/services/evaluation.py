"""Deterministic offline recommendation evaluation using synthetic temporary libraries.

This is a developer diagnostic, not a listening-quality benchmark. It never
loads the owner's config, database, Plex server, or enrichment credentials.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.db.models import Artist, Genre, Style, Track, TrackStats
from musicseed.db.session import init_db
from musicseed.recommender.candidates import build_candidate_pool
from musicseed.recommender.playlist import Recommendation, _track_load_options, recommend_tracks
from musicseed.recommender.populate import _average_score, populate_playlist_recommendations
from musicseed.recommender.scoring import SIGNALS, Weights, build_seed_profile, calculate_score
from musicseed.sonic import SonicVectors

FIXTURE_VERSION = 1
BASELINE_WEIGHTS = Weights(sonic=0.8, novelty=0.2, popularity=0, style=0, genre=0, era=0)


class FixtureTrack(BaseModel):
    """Public synthetic facts only; no private library exports or file paths."""

    id: int
    artist_id: int | None
    year: int | None = None
    popularity: float | None = None
    plays: int | None = None
    styles: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    vector: list[float] | None = None


class EvaluationRequest(BaseModel):
    """Scoring, eligibility and selection controls recorded alongside the metrics."""

    seed_ids: list[int]
    limit: int = 10
    artist_max: int = 2
    year_min: int | None = None
    year_max: int | None = None
    min_score: float | None = None
    weights: Weights = Field(default_factory=Weights)
    mode: Literal["recommend", "average", "frequency"] = "recommend"
    per_seed_limit: int = 12


class EvaluationCase(EvaluationRequest):
    """Synthetic library facts and the complete recommendation request to evaluate."""

    name: str
    description: str
    tracks: list[FixtureTrack]


class StrategyMetrics(BaseModel):
    """Constraint, fill, overlap and evidence metrics under one strategy's objective."""

    selected_ids: list[int]
    returned: int
    fill_rate: float
    oracle_top_k_overlap: float | None
    mean_native_score: float | None
    unique_artists: int
    duplicate_count: int
    seed_overlap_count: int
    year_violation_count: int
    artist_cap_excess: int
    threshold_violation_count: int
    nonfinite_score_count: int
    availability_counts: dict[str, dict[str, int]]


class CaseEvaluation(BaseModel):
    """Three strategy results and a bounded-retrieval diagnostic for one fixture."""

    name: str
    description: str
    fixture_sha256: str
    request: EvaluationRequest
    mode: str
    requested: int
    eligible_count: int
    bounded_candidate_count: int
    bounded_oracle_top_k_recall: float | None
    bounded_missing_oracle_ids: list[int]
    strategies: dict[str, StrategyMetrics]
    observations: list[str]
    invariants_ok: bool


class EvaluationReport(BaseModel):
    """Reproducible synthetic results; intentionally not a musical-preference verdict."""

    fixture_version: int = FIXTURE_VERSION
    seed: int
    listening_preference: Literal["unmeasured"] = "unmeasured"
    baseline_weights: Weights = BASELINE_WEIGHTS
    cases: list[CaseEvaluation]
    invariants_ok: bool


def _vector(first: float, second: float = 0) -> list[float]:
    return [first, second, *([0.0] * 48)]


def evaluation_cases(seed: int = 7) -> list[EvaluationCase]:
    """Nine versioned synthetic cases, reproducible from a nonnegative RNG seed."""
    if seed < 0:
        raise ValueError("seed must be nonnegative")
    rng = np.random.default_rng(seed)
    dense = []
    for i in range(1, 121):
        group = (i - 1) % 6
        embedding = rng.normal(0, 0.03, 50)
        embedding[group] += 1
        dense.append(
            FixtureTrack(
                id=i,
                artist_id=(i - 1) % 24 + 1,
                year=1980 + (i % 40),
                popularity=float(i % 101),
                plays=i % 17,
                styles=[f"style-{group}", "shared"],
                genres=[f"genre-{group % 3}"],
                vector=embedding.tolist(),
            )
        )
    sparse = [
        FixtureTrack(
            id=i,
            artist_id=i % 15,
            plays=None if i % 4 else i,
            vector=_vector(1, i / 100) if i > 2 and i % 3 else None,
        )
        for i in range(1, 81)
    ]
    sparse[-1] = sparse[-1].model_copy(update={"vector": _vector(0)})
    narrow = [FixtureTrack(id=i, artist_id=i, year=1980, vector=_vector(1)) for i in range(1, 72)]
    narrow += [
        FixtureTrack(id=i, artist_id=i, year=2001, vector=_vector(1, i / 100))
        for i in range(72, 84)
    ]
    large_seeds = [FixtureTrack(id=i, artist_id=i) for i in range(1, 81)]
    style = [FixtureTrack(id=1, artist_id=1, styles=["art", "alternative"])]
    style += [FixtureTrack(id=i, artist_id=i, styles=["alternative"]) for i in range(2, 63)]
    style.append(FixtureTrack(id=63, artist_id=63, styles=["art", "alternative"]))
    artist_limited = [FixtureTrack(id=i, artist_id=1, vector=_vector(1)) for i in range(1, 21)]
    return [
        EvaluationCase(
            name="dense",
            description="Complete synthetic metadata and clustered vectors.",
            tracks=dense,
            seed_ids=[1, 7],
            limit=10,
        ),
        EvaluationCase(
            name="sparse",
            description="Unknown tags/year/popularity and missing/zero vectors.",
            tracks=sparse,
            seed_ids=[1, 2],
            limit=10,
        ),
        EvaluationCase(
            name="narrow_era",
            description="Global sonic neighbors lie outside the year window.",
            tracks=narrow,
            seed_ids=[1],
            limit=5,
            year_min=2000,
            year_max=2002,
        ),
        EvaluationCase(
            name="large_seed_set",
            description="Seeds exhaust a post-exclusion source budget.",
            tracks=large_seeds,
            seed_ids=list(range(1, 71)),
            limit=5,
        ),
        EvaluationCase(
            name="perfect_style",
            description="Perfect style match appears after unordered limits.",
            tracks=style,
            seed_ids=[1],
            limit=1,
            weights=Weights(sonic=0, popularity=0, style=1, genre=0, era=0, novelty=0),
        ),
        EvaluationCase(
            name="artist_capacity",
            description="Artist cap legitimately prevents full output.",
            tracks=artist_limited,
            seed_ids=[1],
            limit=8,
            artist_max=2,
        ),
        EvaluationCase(
            name="empty_window",
            description="No eligible release years; empty output is valid.",
            tracks=dense,
            seed_ids=[1],
            year_min=2100,
            year_max=2101,
        ),
        EvaluationCase(
            name="populate_average",
            description="Aggregate playlist profile with a score floor.",
            tracks=dense,
            seed_ids=[1, 7, 13],
            mode="average",
            min_score=0.55,
        ),
        EvaluationCase(
            name="populate_frequency",
            description="Per-seed votes with partial evidence.",
            tracks=sparse,
            seed_ids=[1, 2, 4],
            mode="frequency",
            limit=8,
        ),
    ]


def _load_fixture(context: MusicSeedContext, case: EvaluationCase) -> SonicVectors:
    init_db(context)
    with context.session() as session:
        artists = {
            i: Artist(id=i, name=f"Synthetic artist {i}")
            for i in sorted({t.artist_id for t in case.tracks if t.artist_id is not None})
        }
        styles = {s: Style(name=s) for s in sorted({s for t in case.tracks for s in t.styles})}
        genres = {g: Genre(name=g) for g in sorted({g for t in case.tracks for g in t.genres})}
        for fixture in case.tracks:
            session.add(
                Track(
                    id=fixture.id,
                    plex_id=10000 + fixture.id,
                    title=f"Synthetic track {fixture.id}",
                    artist=artists.get(fixture.artist_id),
                    year=fixture.year,
                    popularity_score=fixture.popularity / 100
                    if fixture.popularity is not None
                    else None,
                    styles=[styles[s] for s in fixture.styles],
                    genres=[genres[g] for g in fixture.genres],
                    stats=TrackStats(play_count=fixture.plays)
                    if fixture.plays is not None
                    else None,
                )
            )
    with_vectors = [t for t in case.tracks if t.vector is not None]
    matrix = np.asarray([t.vector for t in with_vectors], dtype=np.float32).reshape((-1, 50))
    return SonicVectors([10000 + t.id for t in with_vectors], matrix)


def _eligible(track: Track, case: EvaluationCase) -> bool:
    return (
        track.id not in case.seed_ids
        and (case.year_min is None or (track.year is not None and track.year >= case.year_min))
        and (case.year_max is None or (track.year is not None and track.year <= case.year_max))
    )


def _select(
    records: list[Recommendation], limit: int, artist_max: int, min_score: float | None
) -> list[Recommendation]:
    """Small independent greedy selector; ID is the explicit final tiebreaker."""
    selected = []
    artist_counts: Counter = Counter()
    for rec in sorted(records, key=lambda r: (-r.score.total, -len(r.sources), r.track.id)):
        if min_score is not None and rec.score.total < min_score:
            continue
        if artist_counts[rec.track.artist_id] < artist_max:
            selected.append(rec)
            artist_counts[rec.track.artist_id] += 1
            if len(selected) == limit:
                break
    return selected


def _exhaustive(
    tracks: list[Track], vectors: SonicVectors, case: EvaluationCase, weights: Weights
) -> list[Recommendation]:
    """Oracle shares production scoring, but never uses bounded candidate retrieval.

    Frequency mode excludes the complete playlist before per-seed vote budgets.
    This is a retrieval/selection oracle, not independent musical ground truth.
    """
    by_id = {track.id: track for track in tracks}
    eligible = [track for track in tracks if _eligible(track, case)]

    def score(seeds: list[int]) -> list[Recommendation]:
        profile = build_seed_profile([by_id[i] for i in seeds], vectors)
        return [
            Recommendation(
                track=track,
                score=calculate_score(track, profile, weights, vectors),
                sources=["exhaustive"],
            )
            for track in eligible
        ]

    if case.mode != "frequency":
        return _select(score(case.seed_ids), case.limit, case.artist_max, case.min_score)
    votes: dict[int, list[tuple[int, Recommendation]]] = defaultdict(list)
    for seed_id in case.seed_ids:
        for rec in _select(score([seed_id]), case.per_seed_limit, case.artist_max, None):
            votes[rec.track.id].append((seed_id, rec))
    averaged = [
        Recommendation(
            track=by_id[track_id],
            score=_average_score([r.score for _, r in recs]),
            sources=[str(seed_id) for seed_id, _ in recs],
        )
        for track_id, recs in votes.items()
    ]
    return _select(averaged, case.limit, case.artist_max, case.min_score)


def _current(session: Session, vectors: SonicVectors, case: EvaluationCase) -> list[Recommendation]:
    kwargs = dict(
        limit=case.limit,
        weights=case.weights,
        year_min=case.year_min,
        year_max=case.year_max,
        max_tracks_per_artist=case.artist_max,
        min_score=case.min_score,
        vectors=vectors,
    )
    if case.mode == "recommend":
        return recommend_tracks(session, seed_ids=case.seed_ids, **kwargs)[1]
    return populate_playlist_recommendations(
        session, case.seed_ids, method=case.mode, per_seed_limit=case.per_seed_limit, **kwargs
    )


def _metrics(
    records: list[Recommendation], oracle: list[Recommendation], case: EvaluationCase
) -> StrategyMetrics:
    ids = [r.track.id for r in records]
    oracle_ids = {r.track.id for r in oracle}
    artists = Counter(r.track.artist_id for r in records)
    availability = {
        s: dict(sorted(Counter(r.score.availability.get(s, "unknown") for r in records).items()))
        for s in SIGNALS
    }
    return StrategyMetrics(
        selected_ids=ids,
        returned=len(ids),
        fill_rate=len(ids) / case.limit,
        oracle_top_k_overlap=len(set(ids) & oracle_ids) / len(oracle_ids) if oracle_ids else None,
        mean_native_score=round(sum(r.score.total for r in records) / len(records), 12)
        if records
        else None,
        unique_artists=len({r.track.artist_id for r in records if r.track.artist_id is not None}),
        duplicate_count=len(ids) - len(set(ids)),
        seed_overlap_count=len(set(ids) & set(case.seed_ids)),
        year_violation_count=sum(
            not _eligible(r.track, case) and r.track.id not in case.seed_ids for r in records
        ),
        artist_cap_excess=sum(max(0, n - case.artist_max) for n in artists.values()),
        threshold_violation_count=sum(
            case.min_score is not None and r.score.total < case.min_score for r in records
        ),
        nonfinite_score_count=sum(
            not all(math.isfinite(getattr(r.score, s)) for s in ("total", *SIGNALS))
            for r in records
        ),
        availability_counts=availability,
    )


def _evaluate_case(context: MusicSeedContext, case: EvaluationCase) -> CaseEvaluation:
    vectors = _load_fixture(context, case)
    with context.session() as session:
        tracks = session.query(Track).options(*_track_load_options()).order_by(Track.id).all()
        by_id = {t.id: t for t in tracks}
        current = _current(session, vectors, case)
        oracle = _exhaustive(tracks, vectors, case, case.weights)
        baseline = _exhaustive(tracks, vectors, case, BASELINE_WEIGHTS)
        # Diagnostic reference to the original bounded retrieval; union for frequency votes.
        seed_sets = [[i] for i in case.seed_ids] if case.mode == "frequency" else [case.seed_ids]
        bounded_ids: set[int] = set()
        for seeds in seed_sets:
            profile = build_seed_profile([by_id[i] for i in seeds], vectors)
            pool = build_candidate_pool(
                session,
                profile,
                vectors,
                limit=case.per_seed_limit if case.mode == "frequency" else case.limit,
                year_min=case.year_min,
                year_max=case.year_max,
            )
            bounded_ids.update(pool.track_ids)
        bounded_ids.difference_update(case.seed_ids)
        oracle_ids = {r.track.id for r in oracle}
        missing = sorted(oracle_ids - bounded_ids)
        strategies = {
            name: _metrics(records, oracle, case)
            for name, records in (
                ("current", current),
                ("sonic_novelty_baseline", baseline),
                ("exhaustive_oracle", oracle),
            )
        }
        observations = []
        if missing:
            observations.append("bounded retrieval omits current-score oracle selections")
        if len(current) < len(oracle):
            observations.append("current pipeline returns fewer tracks than the oracle")
        if len(oracle) < case.limit:
            observations.append("oracle also underfills: eligibility, threshold or artist capacity")
        safe = all(
            m.returned <= case.limit
            and not any(
                (
                    m.duplicate_count,
                    m.seed_overlap_count,
                    m.year_violation_count,
                    m.artist_cap_excess,
                    m.threshold_violation_count,
                    m.nonfinite_score_count,
                )
            )
            for m in strategies.values()
        )
        return CaseEvaluation(
            name=case.name,
            description=case.description,
            fixture_sha256=hashlib.sha256(
                json.dumps(
                    case.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            request=EvaluationRequest.model_validate(
                case.model_dump(exclude={"name", "description", "tracks"})
            ),
            mode=case.mode,
            requested=case.limit,
            eligible_count=sum(_eligible(t, case) for t in tracks),
            bounded_candidate_count=len(bounded_ids),
            bounded_oracle_top_k_recall=(
                len(oracle_ids & bounded_ids) / len(oracle_ids) if oracle_ids else None
            ),
            bounded_missing_oracle_ids=missing,
            strategies=strategies,
            observations=observations,
            invariants_ok=safe,
        )


def evaluate_recommendations(
    *,
    seed: int = 7,
    case_names: set[str] | None = None,
) -> EvaluationReport:
    """Evaluate disposable synthetic libraries and return deterministic JSON-safe metrics.

    Timestamps, elapsed times and temporary paths are intentionally absent.
    Retrieval gaps are observations, not safety-invariant failures. Native
    scores use different objectives across strategies and are not preference
    ratings. No owner library/context argument is accepted by this diagnostic.
    """
    cases = evaluation_cases(seed)
    if case_names is not None:
        unknown = case_names - {case.name for case in cases}
        if unknown or not case_names:
            raise ValueError(f"Choose known evaluation cases; unknown={sorted(unknown)}")
        cases = [case for case in cases if case.name in case_names]
    results = []
    with TemporaryDirectory(prefix="musicseed-evaluation-") as directory:
        for case in cases:
            context = MusicSeedContext(
                Config.model_validate(
                    {
                        "database": {"path": str(Path(directory) / f"{case.name}.db")},
                        "plex": {"db_path": str(Path(directory) / "unused-plex.db"), "token": ""},
                    }
                )
            )
            try:
                results.append(_evaluate_case(context, case))
            finally:
                context.engine.dispose()
    return EvaluationReport(
        seed=seed, cases=results, invariants_ok=all(r.invariants_ok for r in results)
    )
