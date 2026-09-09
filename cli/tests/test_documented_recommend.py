"""A focused docs-drift sensor; parse examples without invoking a service or config callback."""

import re
import shlex
from pathlib import Path

import pytest
from musicseed_cli.app import app
from typer.main import get_command


def validate_recommend_examples(text: str) -> int:
    command = get_command(app).commands["recommend"]
    examples = re.findall(r"\bmusicseed-cli recommend\b([^`\n]*)", text)
    for suffix in examples:
        try:
            with command.make_context("recommend", shlex.split(suffix, comments=True)):
                pass  # Parse only; never invoke services or the configuration callback.
        except Exception as exc:
            # Typer may vendor its parser; do not depend on standalone click or private imports.
            raise ValueError(f"Invalid documented recommend arguments: {suffix}") from exc
    return len(examples)


def test_documented_recommend_examples_match_actual_typer_options():
    root = Path(__file__).resolve().parents[2]
    for relative in ("docs/resolvers/recommendation-resolvers.md", "cli/AGENTS.md"):
        assert validate_recommend_examples((root / relative).read_text()) > 0


def test_drift_sensor_rejects_an_intentionally_stale_flag():
    with pytest.raises(ValueError, match="Invalid documented"):
        validate_recommend_examples("`musicseed-cli recommend --dry-run`")
