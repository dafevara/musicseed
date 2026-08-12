"""Dashboard aggregation: no Plex server check on the default (cheap) path."""

import musicseed.config as config_module
import pytest
from musicseed.config import Config, set_config
from musicseed.db.session import reset_engine
from musicseed.services.dashboard import get_dashboard
from musicseed.services.discovery import Reason, discover


@pytest.fixture(autouse=True)
def isolated_config(tmp_path):
    cfg = Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    set_config(cfg)
    reset_engine()
    yield
    config_module._config = None
    reset_engine()


def test_discover_without_server_check_skips_plex_http():
    result = discover(check_server=False)
    assert result.plex_server.reason == Reason.SKIPPED
    assert result.plex_server.ok is False


def test_get_dashboard_defaults_to_no_server_check():
    snapshot = get_dashboard()
    assert snapshot.discovery.plex_server.reason == Reason.SKIPPED
    assert snapshot.library.track_count == 0


def test_get_dashboard_can_force_server_check():
    snapshot = get_dashboard(check_server=True)
    assert snapshot.discovery.plex_server.reason != Reason.SKIPPED
