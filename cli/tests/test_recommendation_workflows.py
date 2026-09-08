"""CLI explanations and confirm/apply workflows over real temporary service DTOs."""

import pytest
import typer
from musicseed.clients.plex import MediaItem, Playlist
from musicseed.config import Config, set_config
from musicseed.context import get_context, reset_context
from musicseed.db.models import Album, Artist, Track, TrackVector
from musicseed.db.session import init_db
from musicseed.services import playlist_tracks, populate, recommend
from musicseed_cli.commands import playlist as playlist_command
from musicseed_cli.commands import populate as populate_command
from musicseed_cli.commands import recommend as recommend_command
from musicseed_cli.console import console
from typer.testing import CliRunner


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    set_config(Config.model_validate({
        "database": {"path": str(tmp_path / "cli.db")}, "plex": {"token": "fixture"},
    }))
    ctx = get_context()
    init_db(ctx)
    with ctx.session() as session:
        session.add_all([
            Track(id=1, title="Seed", plex_id=101, artist=Artist(name="Seed Artist")),
            Track(id=2, title="Missing", plex_id=102, artist=Artist(name="Other Artist")),
            Track(id=3, title="Candidate", plex_id=103, artist=Artist(name="Real Artist"),
                  album=Album(title="Real Album"), year=2001, popularity_score=0.7),
            TrackVector(plex_id=101, vector=[1.0] * 50),
            TrackVector(plex_id=103, vector=[1.0] * 50),
        ])

    class FakePlex:
        created = []
        added = []

        def list_playlists(self):
            return [Playlist(rating_key="fixture", title="Fixture", leaf_count=2)]

        def get_playlist(self, _id):
            return self.list_playlists()[0]

        def get_playlist_tracks(self, _id):
            return [MediaItem(rating_key="101"), MediaItem(rating_key="102")]

        def create_playlist(self, name, ids):
            self.created.append(list(ids))
            return Playlist(rating_key="new", title=name, leaf_count=len(ids))

        def add_to_playlist(self, _id, ids):
            self.added.append(list(ids))

    plex = FakePlex()
    monkeypatch.setattr(populate, "_plex_client", lambda _ctx=None: plex)
    monkeypatch.setattr(playlist_tracks, "PlexClient", lambda **_kw: plex)
    monkeypatch.setattr(console, "width", 250)
    app = typer.Typer()
    recommend_command.register(app)
    playlist_command.register(app)
    populate_command.register(app)
    yield app, plex
    ctx.engine.dispose()
    reset_context()


def test_recommend_cli_renders_detached_track_metadata_and_explanations(workflow):
    app, plex = workflow
    result = CliRunner().invoke(app, ["recommend", "--seed-id", "1", "--seed-id", "2", "--explain"])
    assert result.exit_code == 0, result.output
    assert "Real Artist" in result.output and "Candidate" in result.output
    assert "2001" in result.output and "70" in result.output
    assert "n/a:" in result.output
    assert not plex.created and not plex.added


def test_playlist_confirmation_writes_the_displayed_selection_once(workflow, monkeypatch):
    app, plex = workflow
    original = recommend.get_recommendations
    calls = []

    def once(**kwargs):
        assert not calls, "recommendations must not be regenerated after approval"
        calls.append(True)
        return original(**kwargs)

    monkeypatch.setattr(recommend, "get_recommendations", once)
    result = CliRunner().invoke(app, ["playlist", "--name", "Approved", "--seed-id", "1",
                                     "--seed-id", "2", "--explain"], input="y\n")
    assert result.exit_code == 0, result.output
    assert plex.created == [[101, 102, 103]]
    assert len(calls) == 1


@pytest.mark.parametrize("method", ["average", "frequency"])
def test_populate_uses_preview_ids_and_preserves_explanations(workflow, monkeypatch, method):
    app, plex = workflow
    original = populate.populate_playlist_recommendations
    calls = []

    def once(*args, **kwargs):
        assert not calls, "populate must not regenerate after approval"
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(populate, "populate_playlist_recommendations", once)
    result = CliRunner().invoke(app, ["populate", "--playlist", "Fixture", "--method", method,
                                     "--explain"], input="y\n")
    assert result.exit_code == 0, result.output
    assert plex.added == [[103]]
    assert len(calls) == 1
    if method == "frequency":
        assert "mixed evidence:" in result.output


def test_populate_dry_run_never_writes(workflow):
    app, plex = workflow
    result = CliRunner().invoke(app, ["populate", "--playlist", "Fixture", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert not plex.added and not plex.created
