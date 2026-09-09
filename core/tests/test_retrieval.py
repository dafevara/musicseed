"""Exact streaming selection, score parity, and bounded ORM/SQL materialization."""

from collections import Counter

import numpy as np
import pytest
from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.db.models import Track, TrackVector
from musicseed.recommender.playlist import (
    _track_load_options,
    recommend_from_profile,
    recommend_tracks,
    resolve_seed_tracks,
)
from musicseed.recommender.populate import populate_playlist_recommendations
from musicseed.recommender.retrieval import FEATURE_BATCH_SIZE, ConstrainedTopK, ScoredTrack
from musicseed.recommender.scoring import (
    ScoreBreakdown,
    Weights,
    build_seed_profile,
    popularity_value,
)
from musicseed.services.evaluation import (
    EvaluationCase,
    FixtureTrack,
    _exhaustive,
    _load_fixture,
    evaluation_cases,
)
from sqlalchemy import event


def _context(tmp_path):
    return MusicSeedContext(
        Config.model_validate(
            {
                "database": {"path": str(tmp_path / "fixture.db")},
                "plex": {"db_path": str(tmp_path / "unused.db"), "token": ""},
            }
        )
    )


@pytest.mark.parametrize("limit", [1, 3, 12])
@pytest.mark.parametrize("artist_max", [1, 3, 20])
@pytest.mark.parametrize("vote_ties", [False, True])
def test_streaming_exchange_matches_global_greedy_sort_and_bounds_memory(
    limit, artist_max, vote_ties
):
    rng = np.random.default_rng(7)
    records = [
        ScoredTrack(
            i,
            None if i % 11 == 0 else int(rng.integers(0, 20)),
            ScoreBreakdown(
                total=float(rng.integers(-2, 3)),
                sonic=0.5,
                popularity=0.5,
                style=0.5,
                genre=0.5,
                era=0.5,
                novelty=1,
            ),
            votes=int(rng.integers(0, 4)) if vote_ties else 0,
        )
        for i in range(200)
    ]
    expected = []
    counts = Counter()
    for r in sorted(records, key=lambda r: (-r.score.total, -r.votes, r.id)):
        if counts[r.artist_id] < artist_max:
            expected.append(r.id)
            counts[r.artist_id] += 1
            if len(expected) == limit:
                break
    for order in (records, records[::-1], [records[i] for i in rng.permutation(len(records))]):
        selector = ConstrainedTopK(limit, artist_max)
        for record in order:
            selector.add(record)
            assert len(selector.selected) <= limit
            assert len(selector.heap) <= 2 * limit
            assert sum(map(len, selector.by_artist.values())) == len(selector.selected)
        assert [r.id for r in selector.results()] == expected


@pytest.mark.parametrize("name", [c.name for c in evaluation_cases() if c.mode != "frequency"])
def test_compact_pipeline_matches_exhaustive_orm_scores_and_evidence(tmp_path, name):
    case = next(c for c in evaluation_cases() if c.name == name)
    context = _context(tmp_path)
    try:
        vectors = _load_fixture(context, case)
        with context.session() as session:
            tracks = session.query(Track).options(*_track_load_options()).order_by(Track.id).all()
            by_id = {t.id: t for t in tracks}
            profile = build_seed_profile([by_id[i] for i in case.seed_ids], vectors)
            actual, coverage = recommend_from_profile(
                session,
                profile,
                vectors,
                limit=case.limit,
                weights=case.weights,
                year_min=case.year_min,
                year_max=case.year_max,
                max_tracks_per_artist=case.artist_max,
                min_score=case.min_score,
            )
            expected = _exhaustive(tracks, vectors, case, case.weights)
            assert [r.track.id for r in actual] == [r.track.id for r in expected]
            for result, oracle in zip(actual, expected, strict=True):
                assert result.score == oracle.score
                assert result.sources == ["eligible"]
            assert coverage.candidates >= len(actual)
    finally:
        context.engine.dispose()


def test_seed_exclusion_precedes_budgets_and_only_selected_tracks_load_as_orm(tmp_path):
    context = _context(tmp_path)
    case = EvaluationCase(
        name="batch",
        description="Scalar streaming",
        seed_ids=[1],
        tracks=[FixtureTrack(id=i, artist_id=i % 70, year=2000) for i in range(1, 1600)],
    )
    try:
        vectors = _load_fixture(context, case)
        loaded = []
        bind_counts = []

        def object_loaded(_session, obj):
            if isinstance(obj, Track):
                loaded.append(obj.id)

        def query(_conn, _cursor, _statement, parameters, _context, _many):
            bind_counts.append(len(parameters))

        event.listen(context.engine, "before_cursor_execute", query)
        with context.session() as session:
            event.listen(session, "loaded_as_persistent", object_loaded)
            seeds = resolve_seed_tracks(session, seed_ids=[1])
            actual, coverage = recommend_from_profile(
                session,
                build_seed_profile(seeds, vectors),
                vectors,
                limit=10,
                weights=Weights(),
                exclude_ids=set(range(1, 801)),
            )
            ids = [r.track.id for r in actual]
            assert ids == list(range(801, 811))
            assert coverage.candidates == 799
            assert set(loaded) == {1, *ids}
            assert len(loaded) == 11
            assert max(bind_counts) <= FEATURE_BATCH_SIZE
    finally:
        context.engine.dispose()


@pytest.mark.parametrize(
    "normalized,spotify,expected",
    [
        (0.2, 99, 20.0),
        (0, 99, 0.0),
        (None, 50, 50.0),
        (None, None, None),
        (-0.1, 50, 0.0),
        (1.1, 0, 100.0),
    ],
)
def test_scalar_popularity_projection_preserves_precedence_and_scale(normalized, spotify, expected):
    assert popularity_value(normalized, spotify) == expected


@pytest.mark.parametrize("limit,cap", [(0, 1), (1, 0), (-1, 1)])
def test_invalid_selection_limits_fail(limit, cap):
    with pytest.raises(ValueError):
        ConstrainedTopK(limit, cap)


def test_frequency_excludes_whole_large_playlist_before_votes_and_deduplicates_seeds(tmp_path):
    context = _context(tmp_path)
    case = next(c for c in evaluation_cases() if c.name == "large_seed_set")
    case = case.model_copy(update={"mode": "frequency"})
    try:
        vectors = _load_fixture(context, case)
        with context.session() as session:
            tracks = session.query(Track).options(*_track_load_options()).order_by(Track.id).all()
            expected = _exhaustive(tracks, vectors, case, case.weights)
            actual = populate_playlist_recommendations(
                session,
                [*reversed(case.seed_ids), 1],
                method="frequency",
                limit=5,
                per_seed_limit=case.per_seed_limit,
                vectors=vectors,
            )
            assert (
                [r.track.id for r in actual]
                == [r.track.id for r in expected]
                == list(range(71, 76))
            )
            assert all(r.sources == [str(i) for i in reversed(case.seed_ids)] for r in actual)
    finally:
        context.engine.dispose()


def test_recommend_frequency_matches_populate_and_exhaustive(tmp_path):
    context = _context(tmp_path)
    case = next(c for c in evaluation_cases() if c.name == "large_seed_set")
    case = case.model_copy(update={"mode": "frequency"})
    try:
        vectors = _load_fixture(context, case)
        with context.session() as session:
            tracks = session.query(Track).options(*_track_load_options()).order_by(Track.id).all()
            expected = _exhaustive(tracks, vectors, case, case.weights)
            seeds, actual, coverage = recommend_tracks(
                session,
                seed_ids=[*reversed(case.seed_ids), 1],
                method="frequency",
                limit=5,
                per_seed_limit=case.per_seed_limit,
                vectors=vectors,
            )
            assert [t.id for t in seeds] == [*reversed(case.seed_ids)]
            assert [r.track.id for r in actual] == [r.track.id for r in expected]
            assert all(r.sources == [str(i) for i in reversed(case.seed_ids)] for r in actual)
            assert coverage.candidates >= len(actual)
            populate = populate_playlist_recommendations(
                session,
                [*reversed(case.seed_ids), 1],
                method="frequency",
                limit=5,
                per_seed_limit=case.per_seed_limit,
                vectors=vectors,
            )
            assert [r.track.id for r in populate] == [r.track.id for r in actual]
    finally:
        context.engine.dispose()


def test_unknown_recommendation_method_and_per_seed_limit_fail(tmp_path):
    context = _context(tmp_path)
    case = next(c for c in evaluation_cases() if c.name == "perfect_style")
    try:
        _load_fixture(context, case)
        with context.session() as session:
            with pytest.raises(ValueError, match="Unknown recommendation method"):
                recommend_tracks(session, seed_ids=case.seed_ids, method="median")
            with pytest.raises(ValueError, match="per_seed_limit"):
                recommend_tracks(
                    session, seed_ids=case.seed_ids, method="frequency", per_seed_limit=0
                )
    finally:
        context.engine.dispose()


def test_artist_dominated_prefix_does_not_starve_other_eligible_artists(tmp_path):
    context = _context(tmp_path)
    case = EvaluationCase(
        name="artist_prefix",
        description="Budget is not eligibility",
        seed_ids=[1],
        tracks=[FixtureTrack(id=i, artist_id=1 if i < 62 else i) for i in range(1, 74)],
    )
    try:
        vectors = _load_fixture(context, case)
        with context.session() as session:
            _, actual, _ = recommend_tracks(
                session, seed_ids=[1], vectors=vectors, limit=10, max_tracks_per_artist=2
            )
            assert [r.track.id for r in actual] == [2, 3, *range(62, 70)]
    finally:
        context.engine.dispose()


def test_seed_ids_load_in_bounded_queries_and_preserve_requested_order(tmp_path):
    context = _context(tmp_path)
    case = EvaluationCase(
        name="many_seeds",
        description="Batched seed lookup",
        seed_ids=[1],
        tracks=[FixtureTrack(id=i, artist_id=None) for i in range(1, 706)],
    )
    try:
        _load_fixture(context, case)
        queries = []

        def query(_conn, _cursor, _statement, parameters, _context, _many):
            queries.append(len(parameters))

        event.listen(context.engine, "before_cursor_execute", query)
        with context.session() as session:
            requested = list(range(700, 0, -1))
            actual = resolve_seed_tracks(session, seed_ids=[*requested, 1, 10])
            assert [t.id for t in actual] == requested
            assert len(queries) <= 20 and max(queries) <= FEATURE_BATCH_SIZE
            with pytest.raises(ValueError, match="id=706"):
                resolve_seed_tracks(session, seed_ids=[706, 707])
    finally:
        context.engine.dispose()


def test_services_use_local_vectors_without_source_databases_or_network(tmp_path, monkeypatch):
    import socket

    import musicseed.plex_db_source as source
    import musicseed.sonic as sonic
    from musicseed.services.recommend import get_recommendations

    context = _context(tmp_path)
    case = next(c for c in evaluation_cases() if c.name == "perfect_style")
    try:
        _load_fixture(context, case)
        with context.session() as session:
            session.add_all(
                [TrackVector(plex_id=10000 + i, vector=[1, *([0] * 49)]) for i in (1, 63)]
            )
        context.config.plex.db_ssh_target = "fixture@invalid:/no-source"

        def forbidden(*_args, **_kwargs):
            raise AssertionError("query-time recommendations must not read Plex sources/network")

        monkeypatch.setattr(source, "resolve_plex_dbs", forbidden)
        monkeypatch.setattr(sonic, "load_sonic_vectors", forbidden)
        monkeypatch.setattr(socket, "getaddrinfo", forbidden)
        result = get_recommendations(seed_ids=[1], limit=1, context=context)
        assert result.recommendations[0].track.id == 63
        assert result.recommendations[0].sources == ["eligible"]
    finally:
        context.engine.dispose()
