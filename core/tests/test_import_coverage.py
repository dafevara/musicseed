"""Import coverage vs Plex — no real PMS."""

import musicseed.config as config_module
import pytest
from musicseed.config import Config, set_config
from musicseed.db.session import init_db, reset_engine
from musicseed.services.jobs import complete_job, create_job
from musicseed.services.library import (
    CountCompare,
    ImportCoverage,
    get_import_coverage,
    has_succeeded_import,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path):
    cfg = Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    set_config(cfg)
    reset_engine()
    init_db()
    yield
    config_module._config = None
    reset_engine()


def test_setup_incomplete_when_never_succeeded_and_missing() -> None:
    cov = ImportCoverage(
        artists=CountCompare(plex=10, local=10),
        albums=CountCompare(plex=20, local=5),
        tracks=CountCompare(plex=100, local=40),
        ever_succeeded=False,
    )
    assert cov.setup_incomplete
    assert not cov.complete
    assert cov.albums.missing == 15
    assert cov.tracks.missing == 60


def test_setup_complete_when_import_succeeded_even_if_drift() -> None:
    cov = ImportCoverage(
        artists=CountCompare(plex=10, local=10),
        albums=CountCompare(plex=21, local=20),
        tracks=CountCompare(plex=103, local=100),
        ever_succeeded=True,
    )
    assert not cov.setup_incomplete
    assert not cov.complete


def test_has_succeeded_import_false_by_default() -> None:
    assert has_succeeded_import() is False


def test_has_succeeded_import_after_complete() -> None:
    jid = create_job("import")
    complete_job(jid, "ok")
    assert has_succeeded_import() is True


def test_get_import_coverage_none_when_plex_db_missing() -> None:
    assert get_import_coverage() is None
