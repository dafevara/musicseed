"""CLI smoke tests — app assembly and command registration."""

from musicseed_cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in (
        "init-db", "status", "import", "import-plex-sonic",
        "enrich", "recommend", "playlist", "populate",
    ):
        assert cmd in result.output


def test_help_has_no_web_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "web" not in result.output
    assert "serve" not in result.output


def test_import_reports_remote_snapshot_progress(monkeypatch):
    """A remote import must not sit silent while the snapshot is built/fetched."""
    from musicseed.services import library as library_service

    captured: dict = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        on_progress = kwargs["progress_callback"]
        on_progress(0, 100, "preparing Plex snapshot")
        on_progress(30, 100, "preparing Plex snapshot")
        on_progress(40, 100, "preparing Plex snapshot")  # same 25% step: suppressed
        on_progress(60, 100, "preparing Plex snapshot")
        on_progress(60, 100, "downloading Plex database")
        on_progress(5, 10, "tracks")  # item phases stay quiet
        from musicseed.services.library import ImportResult

        return ImportResult(artists=1, albums=1, tracks=1, play_history=0)

    monkeypatch.setattr(library_service, "import_library", fake_import)

    result = runner.invoke(app, ["import", "--plex-db-ssh", "u@nas:/Plex/Databases"])

    assert result.exit_code == 0
    assert captured["progress_callback"] is not None
    # Coarse steps (25%) only: no per-percent spam.
    assert "Preparing plex snapshot… 0%" in result.output
    assert "Preparing plex snapshot… 25%" in result.output
    assert "Preparing plex snapshot… 50%" in result.output
    assert "Downloading plex database… 50%" in result.output
    assert result.output.count("Preparing plex snapshot… 25%") == 1
    assert "tracks" not in result.output
