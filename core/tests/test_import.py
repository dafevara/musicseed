"""Tests for the Plex importer's interaction with the job progress system."""

import pytest
from musicseed.config import Config, set_config
from musicseed.db.session import get_session, init_db, reset_engine
from musicseed.importers import plex as plex_importers
from musicseed.importers.plex import (
    PlexAlbumRow,
    PlexArtistRow,
    PlexTrackRow,
    import_from_plex,
)
from musicseed.services.jobs import create_job, update_progress


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    import musicseed.services.jobs as jobs_module

    set_config(Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}}))
    reset_engine()
    init_db()
    jobs_module._manager = None
    yield
    reset_engine()


class _FakeImporter:
    """Stands in for PlexImporter — no real Plex database required."""

    def __init__(self, db_path, library_name="Music"):
        pass

    def get_counts(self):
        return {"artists": 1, "albums": 1, "tracks": 1, "play_history": 0}

    def iter_artists(self):
        yield PlexArtistRow(
            id=1, guid="artist-guid", title="Artist", title_sort=None, added_at=None
        )

    def iter_albums(self):
        yield PlexAlbumRow(
            id=1, guid="album-guid", title="Album", title_sort=None,
            parent_id=1, year=2020, studio=None, added_at=None,
        )

    def iter_tracks(self):
        yield PlexTrackRow(
            id=1, guid="track-guid", title="Track", title_sort=None,
            parent_id=1, grandparent_id=1, duration=200000, index=1,
            year=None, album_year=2020, added_at=None, updated_at=None,
        )

    def get_track_file_path(self, track_id):
        return None

    def get_track_tags(self, track_id, album_id=None, artist_id=None):
        return {"mbid": [], "genres": [], "moods": [], "styles": []}

    def get_play_history(self):
        return []

    def close(self):
        pass


def test_import_progress_writes_do_not_deadlock(monkeypatch, tmp_path):
    """The progress callback writes to the jobs table in a separate session.

    The import session must commit (release the write lock) before reporting
    progress, otherwise the two sessions deadlock on SQLite and the import
    fails with "database is locked".
    """
    job_id = create_job("import")
    monkeypatch.setattr(plex_importers, "PlexImporter", _FakeImporter)

    calls = []

    def on_progress(current, total, phase):
        calls.append(phase)
        update_progress(job_id, current, total, f"importing {phase}…")

    with get_session() as session:
        result = import_from_plex(
            session=session,
            plex_db_path=tmp_path / "nonexistent.db",
            progress_callback=on_progress,
        )

    assert result["artists"] == 1
    assert result["albums"] == 1
    assert result["tracks"] == 1
    assert calls == ["artists", "albums", "tracks"]
