"""Handler-layer tests — framework-free, offline."""

import musicseed.config as config_module
import pytest
from musicseed.config import Config, load_config, set_config
from musicseed.db.session import init_db, reset_engine
from musicseed.exceptions import JobConflictError, NotFoundError
from musicseed.services.jobs import create_job
from musicseed.services.populate import PopulateApplyResult
from musicseed_api.handlers.enrichment import save_spotify_creds
from musicseed_api.handlers.jobs import cancel_job, delete_job, get_job_progress
from musicseed_api.handlers.recommend import parse_seed_ids


def test_parse_seed_ids():
    assert parse_seed_ids("1,2,3") == [1, 2, 3]
    assert parse_seed_ids("") == []
    assert parse_seed_ids("abc,def") == []
    assert parse_seed_ids(" 1 , 2 ") == [1, 2]


def test_save_spotify_creds_persists(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("")
    set_config(load_config(cfg_path))

    save_spotify_creds("cid", "secret")

    config_module._config = None
    config_module._config_path = None
    reloaded = load_config(cfg_path)
    assert reloaded.spotify.client_id == "cid"
    assert reloaded.spotify.client_secret == "secret"


def test_save_spotify_creds_noop_when_empty(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("")
    set_config(load_config(cfg_path))

    save_spotify_creds("", "")

    assert config_module._config.spotify.client_id == ""


def test_jobs_handlers(tmp_path):
    import musicseed.services.jobs as jobs_module

    set_config(Config.model_validate({"database": {"path": str(tmp_path / "db.sqlite")}}))
    reset_engine()
    init_db()
    jobs_module._manager = None

    jid = create_job("import")
    assert get_job_progress(jid)["state"] == "pending"

    cancel_job(jid)
    assert get_job_progress(jid)["state"] == "cancel_requested"

    assert get_job_progress(999999) is None


def test_delete_job_handler(tmp_path):
    import musicseed.services.jobs as jobs_module

    set_config(Config.model_validate({"database": {"path": str(tmp_path / "db.sqlite")}}))
    reset_engine()
    init_db()
    jobs_module._manager = None

    # A pending job is active and cannot be deleted.
    pending_id = create_job("import")
    with pytest.raises(JobConflictError):
        delete_job(pending_id)

    # Missing jobs map to NotFoundError.
    with pytest.raises(NotFoundError):
        delete_job(999999)

    # A completed job can be deleted and disappears from the store.
    done_id = create_job("enrich")
    jobs_module.complete_job(done_id)
    delete_job(done_id)
    assert get_job_progress(done_id) is None


def test_apply_populate_passes_selected_track_ids(monkeypatch):
    import musicseed_api.handlers.playlists as playlists_module

    captured = {}

    def fake_populate(**kwargs):
        captured.update(kwargs)
        return PopulateApplyResult(
            playlist_name=kwargs["playlist_name"],
            playlist_track_count=5,
            matched_track_count=3,
            recommendations=[],
            added_count=2,
        )

    monkeypatch.setattr(playlists_module, "populate_playlist", fake_populate)
    result = playlists_module.apply_populate(playlist_name="Test", track_ids=[10, 20])
    assert captured["track_ids"] == [10, 20]
    assert result["added_count"] == 2


def test_save_config_overrides_persists_without_init_db(tmp_path, monkeypatch):
    import musicseed_api.handlers.discovery as discovery_handlers

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("")
    set_config(load_config(cfg_path))

    called = []
    monkeypatch.setattr(discovery_handlers, "initialize_database", lambda: called.append(True))

    changed = discovery_handlers.save_config_overrides(
        plex_url="http://plex.local:32400",
        spotify_client_id="cid",
        spotify_client_secret="secret",
    )

    assert changed
    assert called == []  # saving config never initializes the database

    config_module._config = None
    config_module._config_path = None
    reloaded = load_config(cfg_path)
    assert reloaded.plex.url == "http://plex.local:32400"
    assert reloaded.spotify.client_id == "cid"
    assert reloaded.spotify.client_secret == "secret"


def test_save_config_overrides_leaves_blank_fields_untouched(tmp_path):
    import musicseed_api.handlers.discovery as discovery_handlers

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("")
    set_config(load_config(cfg_path))

    changed = discovery_handlers.save_config_overrides()

    assert not changed
    assert config_module._config.plex.url == "http://localhost:32400"


def test_save_config_overrides_uses_local_token(tmp_path, monkeypatch):
    import musicseed_api.handlers.discovery as discovery_handlers

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("")
    set_config(load_config(cfg_path))

    monkeypatch.setattr(discovery_handlers, "read_plex_token", lambda: "LOCAL-TOKEN")
    changed = discovery_handlers.save_config_overrides()

    assert changed
    assert config_module._config.plex.token == "LOCAL-TOKEN"

    config_module._config = None
    config_module._config_path = None
    reloaded = load_config(cfg_path)
    assert reloaded.plex.token == "LOCAL-TOKEN"


def test_save_config_overrides_keeps_existing_token(tmp_path, monkeypatch):
    import musicseed_api.handlers.discovery as discovery_handlers

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("plex:\n  token: CONFIG-TOKEN\n")
    set_config(load_config(cfg_path))

    monkeypatch.setattr(discovery_handlers, "read_plex_token", lambda: "LOCAL-TOKEN")
    discovery_handlers.save_config_overrides()

    assert config_module._config.plex.token == "CONFIG-TOKEN"


def test_apply_config_and_init_db_initializes(tmp_path, monkeypatch):
    import musicseed_api.handlers.discovery as discovery_handlers

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("")
    set_config(load_config(cfg_path))

    called = []
    monkeypatch.setattr(discovery_handlers, "initialize_database", lambda: called.append(True))
    discovery_handlers.apply_config_and_init_db(plex_url="http://plex.local:32400")
    assert called == [True]


def test_run_plex_discovery_delegates(monkeypatch):
    import musicseed_api.handlers.discovery as discovery_handlers

    captured = {}

    def fake_discover(timeout, token):
        captured["token"] = token
        return "servers"

    monkeypatch.setattr(discovery_handlers, "discover_plex_servers", fake_discover)
    assert discovery_handlers.run_plex_discovery() == "servers"
    # conftest config has no plex token.
    assert captured["token"] == ""
