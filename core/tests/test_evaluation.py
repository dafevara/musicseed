"""Synthetic evaluation invariants, reproducibility, and known bounded retrieval gaps."""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from musicseed.services.evaluation import evaluate_recommendations, evaluation_cases


@pytest.fixture(scope="module")
def report():
    return evaluate_recommendations(seed=7)


def test_report_is_repeatable_and_contains_no_machine_paths_or_preference_claim(report):
    again = evaluate_recommendations(seed=7)
    assert report.model_dump_json() == again.model_dump_json()
    assert report.listening_preference == "unmeasured"
    assert len(report.cases) == 9
    assert all(len(case.fixture_sha256) == 64 for case in report.cases)
    assert "musicseed-evaluation-" not in report.model_dump_json()
    assert evaluation_cases(7)[0].tracks[0].vector != evaluation_cases(8)[0].tracks[0].vector


def test_every_strategy_satisfies_independently_checked_selection_invariants(report):
    fixtures = {case.name: case for case in evaluation_cases(7)}
    assert report.invariants_ok
    for result in report.cases:
        case = fixtures[result.name]
        tracks = {track.id: track for track in case.tracks}
        for metrics in result.strategies.values():
            ids = metrics.selected_ids
            assert metrics.returned == len(ids) <= case.limit
            assert len(ids) == len(set(ids))
            assert not set(ids) & set(case.seed_ids)
            artists = Counter(tracks[i].artist_id for i in ids)
            assert all(count <= case.artist_max for count in artists.values())
            for track_id in ids:
                year = tracks[track_id].year
                if case.year_min is not None:
                    assert year is not None and year >= case.year_min
                if case.year_max is not None:
                    assert year is not None and year <= case.year_max
            for counts in metrics.availability_counts.values():
                assert sum(counts.values()) == len(ids)
            assert metrics.nonfinite_score_count == metrics.threshold_violation_count == 0
            assert metrics.duplicate_count == metrics.seed_overlap_count == 0
            assert metrics.year_violation_count == metrics.artist_cap_excess == 0


def test_report_exposes_omitted_style_match_and_large_seed_budget_starvation(report):
    cases = {case.name: case for case in report.cases}
    style = cases["perfect_style"]
    assert style.bounded_missing_oracle_ids == [63]
    assert style.bounded_oracle_top_k_recall == 0
    assert style.strategies["current"].mean_native_score == 0.5
    assert style.strategies["exhaustive_oracle"].selected_ids == [63]
    assert style.strategies["exhaustive_oracle"].mean_native_score == 1
    large = cases["large_seed_set"]
    assert large.eligible_count == 10
    assert large.bounded_candidate_count == 0
    assert large.strategies["current"].returned == 0
    assert large.strategies["exhaustive_oracle"].returned == 5
    assert large.observations


def test_legitimate_underfill_and_unknown_evidence_are_not_hidden(report):
    cases = {case.name: case for case in report.cases}
    assert cases["artist_capacity"].strategies["exhaustive_oracle"].returned == 2
    empty = cases["empty_window"]
    assert empty.eligible_count == 0 and empty.bounded_oracle_top_k_recall is None
    assert empty.strategies["current"].oracle_top_k_overlap is None
    sparse = cases["sparse"].strategies["current"]
    assert sparse.availability_counts["sonic"] == {"neutral_missing": sparse.returned}
    assert sparse.availability_counts["style"] == {"not_applicable": sparse.returned}
    assert cases["narrow_era"].strategies["current"].returned == 5


def test_evaluation_never_reads_default_context_or_calls_network(monkeypatch):
    import socket

    import musicseed.config as config
    import musicseed.context as context

    def forbidden(*_args, **_kwargs):
        raise AssertionError("synthetic evaluation must not use owner context or network")

    monkeypatch.setattr(config, "get_config", forbidden)
    monkeypatch.setattr(context, "get_config", forbidden)
    monkeypatch.setattr(context, "get_context", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    result = evaluate_recommendations(case_names={"perfect_style", "large_seed_set"})
    assert result.invariants_ok


def test_command_emits_parseable_json_and_fails_invalid_input(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_recommendations.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--case", "perfect_style"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    payload = json.loads(completed.stdout)
    assert payload["cases"][0]["name"] == "perfect_style"
    assert payload["invariants_ok"]
    output = tmp_path / "report.json"
    subprocess.run(
        [sys.executable, str(script), "--case", "perfect_style", "--output", str(output)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert json.loads(output.read_text()) == payload
    invalid = subprocess.run(
        [sys.executable, str(script), "--seed", "-1"], capture_output=True, text=True, timeout=30
    )
    assert invalid.returncode != 0
    assert "nonnegative" in invalid.stderr


@pytest.mark.parametrize("names", [set(), {"unknown"}])
def test_unknown_or_empty_case_selection_fails(names):
    with pytest.raises(ValueError):
        evaluate_recommendations(case_names=names)
