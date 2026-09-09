#!/usr/bin/env python3
"""Run from core/: uv run --no-sync python ../scripts/evaluate_recommendations.py."""

import argparse
from pathlib import Path

from musicseed.services.evaluation import evaluate_recommendations, evaluation_cases


def main() -> int:
    """Write a fixture report and fail only on safety-invariant violations."""
    parser = argparse.ArgumentParser(
        description="Evaluate synthetic recommendations offline (no Plex)."
    )
    parser.add_argument(
        "--seed", type=int, default=7, help="Nonnegative fixture RNG seed (default 7)"
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=[c.name for c in evaluation_cases(0)],
        help="Evaluate only these cases (repeatable)",
    )
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout")
    args = parser.parse_args()
    if args.seed < 0:
        parser.error("--seed must be nonnegative")
    report = evaluate_recommendations(
        seed=args.seed, case_names=set(args.case) if args.case else None
    )
    content = report.model_dump_json(indent=2) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    # Ranking/recall gaps are diagnostic, not safety-invariant failures.
    return 0 if report.invariants_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
