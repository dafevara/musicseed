"""Focused executable-symbol, defaults, diagram and developer-command drift checks."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from musicseed.recommender import playlist, retrieval, scoring

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "resolvers"


def validate_script_flags(arguments: str, help_text: str) -> None:
    mentioned = set(re.findall(r"--[a-z][a-z0-9-]*", arguments))
    supported = set(re.findall(r"--[a-z][a-z0-9-]*", help_text))
    assert not mentioned - supported, f"Stale flags: {sorted(mentioned - supported)}"


@pytest.mark.parametrize("script_name", ["evaluate_recommendations.py", "benchmark_retrieval.py"])
def test_documented_developer_flags_exist_in_actual_help(script_name):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script_name), "--help"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    text = "\n".join(
        (DOCS / name).read_text()
        for name in ("recommendation-evaluation.md", "retrieval-decision.md")
    )
    examples = re.findall(r"python \S*/" + re.escape(script_name) + r"([^\n]*)", text)
    assert examples
    for arguments in examples:
        validate_script_flags(arguments, completed.stdout)
    with pytest.raises(AssertionError, match="Stale flags"):
        validate_script_flags("--obsolete-retrieval-flag", completed.stdout)


def test_changed_diagram_and_documented_symbols_match_the_implementation():
    resolver = (DOCS / "recommendation-resolvers.md").read_text()
    for module, name in (
        (retrieval, "score_eligible_tracks"),
        (playlist, "recommend_from_profile"),
        (scoring, "score_signals"),
        (retrieval, "ConstrainedTopK"),
    ):
        assert f"`{name}" in resolver
        assert callable(getattr(module, name))
    diagram = (ROOT / "docs" / "musicseed-dependency-architecture.html").read_text()
    labels = re.findall(r'class="box-label">([^<]+)</text>', diagram)
    assert "score_eligible_tracks" in labels and "ConstrainedTopK" in labels
    assert "build_candidate_pool" not in labels
    defaults = dict(
        (name, float(value))
        for name, value in re.findall(
            r"^(sonic|popularity|style|genre|era|novelty)=([\d.]+)$", resolver, re.MULTILINE
        )
    )
    assert defaults == scoring.Weights().model_dump()


def test_benchmark_smoke_reports_methodology_and_bounded_materialization(tmp_path):
    output = tmp_path / "benchmark.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "benchmark_retrieval.py"),
            "--sizes",
            "100",
            "--repeats",
            "1",
            "--no-extra-indexes",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    report = json.loads(output.read_text())
    assert report["extra_indexes"] is False
    assert report["listening_preference"] == "unmeasured"
    assert "traced" not in report["rss_source"]
    row = report["measurements"][0]
    full = row["strategies"]["full"]
    assert full["candidate_count"] == 98
    assert full["orm_objects_per_warm_query"]["Track"] == 52
    assert len(full["selected_ids"]) == 50
    assert len(full["warm_query_seconds"]) == 1
    assert full["separate_traced_request_peak_mib"] > 0


def test_checked_in_comparisons_use_identical_inputs():
    directory = ROOT / "docs" / "evaluation"
    old = json.loads((directory / "bounded-v1-seed7.json").read_text())
    new = json.loads((directory / "full-v1-seed7.json").read_text())
    assert old["seed"] == new["seed"] and new["invariants_ok"]
    for before, after in zip(old["cases"], new["cases"], strict=True):
        assert before["fixture_sha256"] == after["fixture_sha256"]
        assert before["request"] == after["request"]
        assert after["strategies"]["current"] == after["strategies"]["exhaustive_oracle"]
    indexed = json.loads((directory / "retrieval-v1-seed7.json").read_text())
    primary = json.loads((directory / "retrieval-no-indexes-v1-seed7.json").read_text())
    assert indexed["weights"] == primary["weights"] and indexed["seed"] == primary["seed"]
    wide = next(row for row in indexed["measurements"] if row["tracks"] == 50000)
    assert (
        wide["strategies"]["full"]["selected_ids"]
        == (primary["measurements"][0]["strategies"]["full"]["selected_ids"])
    )
