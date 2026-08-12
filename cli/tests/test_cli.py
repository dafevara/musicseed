"""CLI smoke tests — app assembly and command registration."""

from musicseed_cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init-db", "status", "import", "enrich", "recommend", "playlist", "populate"):
        assert cmd in result.output


def test_help_has_no_web_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "web" not in result.output
