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
    assert calls == ["artists", "albums", "tracks", "play history"]


@pytest.fixture
def service_import(monkeypatch, tmp_path):
    from musicseed.context import get_context
    from musicseed.services import library

    source = tmp_path / "plex.db"
    source.write_bytes(b"fixture Plex source")
    context = get_context()
    context.config.plex.db_path = str(source)
    monkeypatch.setattr(plex_importers, "PlexImporter", _FakeImporter)
    monkeypatch.setattr(library, "PlexImporter", _FakeImporter)
    return library, context


def test_ssh_import_announces_snapshot_progress(service_import, tmp_path, monkeypatch):
    """A remote import reports the snapshot phases, which are otherwise silent.

    Regression: the UI showed a frozen "downloading Plex database" bar for
    minutes because nothing reported the host's backup step or the transfer.
    """
    from musicseed.plex_db_source import PREPARE_PHASE, ResolvedPlexDbs
    from musicseed.services import library

    _library, context = service_import
    source = tmp_path / "plex.db"
    source.write_bytes(b"fixture Plex source")
    context.config.plex.db_ssh_target = "u@nas:/Plex/Databases"

    def fake_resolve(config, *, refresh=False, ssh_target=None, on_progress=None):
        assert refresh is True, "the import must refresh the snapshot"
        assert on_progress is not None, "the import must forward its progress callback"
        on_progress(40, 100, PREPARE_PHASE)
        on_progress(100, 100, "downloading Plex database")
        return ResolvedPlexDbs(
            library_db=source, blobs_db=source.with_name("blobs.db"), source="ssh"
        )

    monkeypatch.setattr(library, "resolve_plex_dbs", fake_resolve)
    seen: list[tuple[int, int, str]] = []

    library.import_library(
        context=context, progress_callback=lambda c, t, p: seen.append((c, t, p))
    )

    # The phase is announced before the SSH round-trip, then updated with real
    # numbers, then the import phases continue.
    assert seen[0] == (0, 100, PREPARE_PHASE)
    assert (40, 100, PREPARE_PHASE) in seen
    assert (100, 100, "downloading Plex database") in seen
    assert any(phase == "artists" for _c, _t, phase in seen)


def test_local_import_reports_no_snapshot_phase(service_import, tmp_path):
    """Local imports must not claim to be preparing a remote snapshot."""
    from musicseed.plex_db_source import PREPARE_PHASE
    from musicseed.services import library

    _library, context = service_import
    seen: list[str] = []

    library.import_library(context=context, progress_callback=lambda c, t, p: seen.append(p))

    assert PREPARE_PHASE not in seen


def test_source_completion_survives_job_deletion_but_not_source_change(service_import):
    from musicseed.context import MusicSeedContext
    from musicseed.services import jobs
    from musicseed.services.import_state import read_import_state

    library, context = service_import
    result = library.import_library(context=context)
    assert result.tracks == 1
    assert library.has_succeeded_import(context)
    coverage = library.get_import_coverage(context)
    assert coverage.verified and coverage.complete
    state = read_import_state(context)
    assert state["state"] == "complete"
    assert state["snapshot"]
    assert state["checkpoint"] == "finished"
    assert jobs.delete_job(state["job_id"])
    assert library.has_succeeded_import(context)

    different = MusicSeedContext(context.config.model_copy(deep=True))
    different.config.plex.library = "Another Library"
    assert not library.has_succeeded_import(different)
    unverified = library.get_import_coverage(different)
    # Equal aggregate counts must not certify a different source/library.
    assert unverified.tracks.plex == unverified.tracks.local
    assert not unverified.verified and not unverified.complete
    assert unverified.setup_incomplete


def test_canceled_import_keeps_checkpoint_and_resumes_without_duplicates(service_import):
    from musicseed.services import jobs
    from musicseed.services.import_state import read_import_state

    library, context = service_import
    cancel = False

    def progress(_current, _total, phase):
        nonlocal cancel
        if phase == "artists":
            cancel = True

    library.import_library(
        context=context, progress_callback=progress, should_cancel=lambda: cancel,
    )
    state = read_import_state(context)
    assert state["state"] == "canceled"
    assert state["checkpoint"] == "artists"
    assert state["processed"] == 1
    assert jobs.get_job(state["job_id"])["state"] == "canceled"
    assert not library.has_succeeded_import(context)
    assert library.get_import_coverage(context).setup_incomplete

    library.import_library(context=context)
    resumed = library.get_import_coverage(context)
    assert resumed.complete
    assert resumed.artists.local == resumed.albums.local == resumed.tracks.local == 1


def test_failure_does_not_certify_partial_import(service_import):
    from musicseed.services.import_state import read_import_state

    library, context = service_import

    def progress(_current, _total, phase):
        if phase == "albums":
            raise RuntimeError("fixture import failure")

    with pytest.raises(RuntimeError, match="fixture import failure"):
        library.import_library(context=context, progress_callback=progress)
    state = read_import_state(context)
    assert state["state"] == "failed"
    assert state["checkpoint"] == "albums"
    assert state["processed"] == 1
    assert not library.has_succeeded_import(context)
    library.import_library(context=context)
    assert library.get_import_coverage(context).complete
