"""Handler-layer tests — framework-free, offline."""

import musicseed.config as config_module
from musicseed.config import Config, load_config, set_config
from musicseed.db.session import init_db, reset_engine
from musicseed.services.jobs import create_job
from musicseed_api.handlers.enrichment import save_spotify_creds
from musicseed_api.handlers.jobs import cancel_job, get_job_progress
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
