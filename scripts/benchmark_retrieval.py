#!/usr/bin/env python3
"""Offline retrieval benchmark; all databases/vectors are generated in a temporary directory."""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import resource
import sqlite3
import statistics
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.db.models import (
    Album,
    Artist,
    Genre,
    Style,
    Track,
    TrackGenre,
    TrackStats,
    TrackStyle,
)
from musicseed.db.session import create_indexes, init_db
from musicseed.recommender.candidates import build_candidate_pool
from musicseed.recommender.playlist import (
    Recommendation,
    _track_load_options,
    recommend_from_profile,
    resolve_seed_tracks,
)
from musicseed.recommender.scoring import Weights, build_seed_profile, calculate_score
from musicseed.services.evaluation import _select
from musicseed.sonic import SonicVectors
from sqlalchemy import event


def _context(directory: Path) -> MusicSeedContext:
    return MusicSeedContext(
        Config.model_validate(
            {
                "database": {"path": str(directory / "library.db")},
                "plex": {"db_path": str(directory / "unused-plex.db"), "token": ""},
            }
        )
    )


def _insert(connection, model, rows):
    if rows:
        connection.execute(model.__table__.insert(), rows)


def _fixture(directory: Path, size: int, seed: int, *, extra_indexes: bool = True) -> None:
    context = _context(directory)
    init_db(context)
    artist_count = max(20, size // 12)
    with context.engine.begin() as connection:
        connection.execute(
            Artist.__table__.insert(),
            [{"id": i, "name": f"Synthetic artist {i}"} for i in range(1, artist_count + 1)],
        )
        connection.execute(
            Album.__table__.insert(),
            [
                {"id": i, "artist_id": i, "title": f"Synthetic album {i}"}
                for i in range(1, artist_count + 1)
            ],
        )
        connection.execute(
            Style.__table__.insert(), [{"id": i, "name": f"style-{i}"} for i in range(1, 14)]
        )
        connection.execute(
            Genre.__table__.insert(), [{"id": i, "name": f"genre-{i}"} for i in range(1, 5)]
        )
        for start in range(1, size + 1, 1000):
            ids = range(start, min(size + 1, start + 1000))
            connection.execute(
                Track.__table__.insert(),
                [
                    {
                        "id": i,
                        "plex_id": 10000 + i,
                        "title": f"Synthetic track {i}",
                        "artist_id": (i - 1) % artist_count + 1,
                        "album_id": (i - 1) % artist_count + 1,
                        "year": 1980 + i % 45 if i % 11 else None,
                        "popularity_score": i % 101 / 100 if i % 7 else None,
                        "file_path": "/synthetic-not-real/" + "metadata-padding/" * 8 + str(i),
                    }
                    for i in ids
                ],
            )
            _insert(
                connection,
                TrackStyle,
                [
                    {"track_id": i, "style_id": tag}
                    for i in ids
                    if i % 7
                    for tag in ((i - 1) % 12 + 1, 13)
                ],
            )
            _insert(
                connection,
                TrackGenre,
                [{"track_id": i, "genre_id": (i - 1) % 4 + 1} for i in ids if i % 7],
            )
            _insert(
                connection,
                TrackStats,
                [{"track_id": i, "play_count": i % 23} for i in ids if i % 13],
            )
    if extra_indexes:
        assert all(result.success for result in create_indexes(context))
    context.engine.dispose()
    rng = np.random.default_rng(seed)
    matrix = rng.normal(0, 0.03, (size, 50)).astype(np.float32)
    matrix[np.arange(size), np.arange(size) % 12] += 1
    mask = np.arange(1, size + 1) % 5 != 0
    np.save(directory / "vectors.npy", matrix[mask])


def _rss_mib() -> float:
    # Linux ru_maxrss can retain the parent's pre-exec launch footprint. VmHWM
    # describes this executable's address space instead; neither is request-only.
    if sys.platform == "linux":
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
        raise RuntimeError("VmHWM is unavailable for this benchmark worker")
    divisor = 1024**2 if sys.platform == "darwin" else 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor


def _worker(args) -> dict:
    context = _context(args.fixture)
    size = args.sizes[0]
    ids = np.arange(1, size + 1)
    vectors = SonicVectors(
        (10000 + ids[ids % 5 != 0]).tolist(), np.load(args.fixture / "vectors.npy")
    )
    before_rss = _rss_mib()
    query_count = 0
    loaded: dict[str, int] = {}

    def count_query(*_args):
        nonlocal query_count
        query_count += 1

    def count_object(_session, instance):
        name = type(instance).__name__
        loaded[name] = loaded.get(name, 0) + 1

    event.listen(context.engine, "before_cursor_execute", count_query)
    year_min, year_max = args.year_window or (None, None)
    pool_ids: list[int] = []
    candidate_count = 0

    def run():
        nonlocal pool_ids, candidate_count
        with context.session() as session:
            event.listen(session, "loaded_as_persistent", count_object)
            seeds = resolve_seed_tracks(session, seed_ids=[1, 13])
            profile = build_seed_profile(seeds, vectors)
            weights = Weights()
            if args.worker == "full":
                records, coverage = recommend_from_profile(
                    session,
                    profile,
                    vectors,
                    limit=50,
                    weights=weights,
                    max_tracks_per_artist=3,
                    year_min=year_min,
                    year_max=year_max,
                )
                candidate_count = coverage.candidates
            else:
                pool = build_candidate_pool(
                    session, profile, vectors, limit=50, year_min=year_min, year_max=year_max
                )
                pool_ids = pool.track_ids
                candidate_count = len(pool_ids)
                tracks = (
                    session.query(Track)
                    .options(*_track_load_options())
                    .filter(Track.id.in_(pool_ids))
                    .all()
                )
                records = _select(
                    [
                        Recommendation(
                            track=t,
                            score=calculate_score(t, profile, weights, vectors),
                            sources=["bounded_reference"],
                        )
                        for t in tracks
                    ],
                    50,
                    3,
                    None,
                )
            return [(r.track.id, r.score.total) for r in records]

    elapsed = []
    expected = None
    for _ in range(args.repeats + 1):
        gc.collect()
        query_count = 0
        loaded.clear()
        start = time.perf_counter()
        selected = run()
        elapsed.append(time.perf_counter() - start)
        if expected is None:
            expected = selected
        assert selected == expected, "selection changed between identical requests"
    query_counts = query_count
    objects = dict(loaded)
    peak_rss = _rss_mib()  # Excludes the later tracemalloc-instrumented pass.
    gc.collect()
    tracemalloc.start()
    run()
    _, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    context.engine.dispose()
    return {
        "strategy": args.worker,
        "candidate_count": candidate_count,
        "selected_ids": [i for i, _ in expected],
        "mean_score": round(statistics.mean(score for _, score in expected), 12)
        if expected
        else None,
        "first_query_seconds": elapsed[0],
        "warm_query_seconds": elapsed[1:],
        "warm_median_seconds": statistics.median(elapsed[1:]),
        "before_queries_peak_rss_mib": before_rss,
        "process_peak_rss_mib": peak_rss,
        "separate_traced_request_peak_mib": traced_peak / 1024**2,
        "sql_statements_per_warm_query": query_counts,
        "orm_objects_per_warm_query": objects,
        "bounded_pool_ids": pool_ids,
    }


def main() -> int:
    """Benchmark fresh single-threaded workers, keeping fixtures and cache setup out of timings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 50000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--year-window", nargs=2, type=int)
    parser.add_argument(
        "--no-extra-indexes",
        action="store_true",
        help="Use only normal initialization's primary/unique indexes",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=["bounded", "full"], help=argparse.SUPPRESS)
    parser.add_argument("--fixture", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.sizes) < 50 or args.repeats < 1 or args.seed < 0:
        parser.error("sizes must be >= 50, repeats >= 1, and seed >= 0")
    if len(args.sizes) != len(set(args.sizes)):
        parser.error("sizes must be distinct")
    if args.worker:
        print(json.dumps(_worker(args)))
        return 0
    measurements = []
    with TemporaryDirectory(prefix="musicseed-benchmark-") as directory:
        for size in args.sizes:
            fixture = Path(directory) / str(size)
            fixture.mkdir(exist_ok=True)
            _fixture(fixture, size, args.seed, extra_indexes=not args.no_extra_indexes)
            strategies = {}
            for strategy in ("bounded", "full"):
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    strategy,
                    "--fixture",
                    str(fixture),
                    "--sizes",
                    str(size),
                    "--repeats",
                    str(args.repeats),
                ]
                if args.year_window:
                    command += ["--year-window", *map(str, args.year_window)]
                env = {
                    **os.environ,
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "VECLIB_MAXIMUM_THREADS": "1",
                }
                completed = subprocess.run(
                    command, env=env, text=True, capture_output=True, check=True, timeout=600
                )
                strategies[strategy] = json.loads(completed.stdout)
            oracle_ids = set(strategies["full"]["selected_ids"])
            bounded_pool = set(strategies["bounded"].pop("bounded_pool_ids"))
            strategies["full"].pop("bounded_pool_ids")
            measurements.append(
                {
                    "tracks": size,
                    "strategies": strategies,
                    "bounded_oracle_top_k_recall": len(oracle_ids & bounded_pool) / len(oracle_ids)
                    if oracle_ids
                    else None,
                }
            )
    report = {
        "fixture_version": 1,
        "seed": args.seed,
        "seed_ids": [1, 13],
        "weights": Weights().model_dump(mode="json"),
        "limit": 50,
        "artist_max": 3,
        "year_window": args.year_window,
        "repeats": args.repeats,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.system(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "worker_blas_threads": 1,
        "extra_indexes": not args.no_extra_indexes,
        "rss_source": "Linux VmHWM since exec"
        if sys.platform == "linux"
        else "getrusage process high-water (may include launch)",
        "listening_preference": "unmeasured",
        "methodology": (
            "Fresh workers; preloaded float32 vectors; fixture/index/cache setup excluded. "
            "First query is not OS-cold. Warm queries use new sessions. RSS is process "
            "high-water including runtime/cache, before tracing. Traced peak is a separate "
            "untimed request and is not all native memory. Full uses exact streaming top-k; "
            "bounded is the original multi-source ORM reference with explicit ID ties."
        ),
        "measurements": measurements,
    }
    content = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
