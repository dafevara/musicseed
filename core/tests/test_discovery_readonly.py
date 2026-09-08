"""Effective overrides and coverage probes must not mutate legacy databases."""

import sqlite3
from contextlib import closing

from musicseed.config import Config
from musicseed.services import discovery, library


def test_discovery_overrides_are_shared_by_coverage_and_do_not_migrate(tmp_path, monkeypatch):
    local = tmp_path / "legacy.db"
    plex = tmp_path / "plex.db"
    with closing(sqlite3.connect(local)) as conn:
        for table in ("artists", "albums", "tracks"):
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            conn.execute(f"INSERT INTO {table} VALUES (1)")
        conn.commit()
        before_schema = conn.execute("SELECT sql FROM sqlite_schema ORDER BY name").fetchall()
    with closing(sqlite3.connect(plex)) as conn:
        conn.execute("CREATE TABLE fixture (id INTEGER)")
    before_content = local.read_bytes()
    seen = []

    class FakeImporter:
        def __init__(self, path, name):
            seen.append((path, name))

        def get_counts(self):
            return {"artists": 1, "albums": 1, "tracks": 1}

        def close(self):
            pass

    def unexpected_ssh(*_args, **_kwargs):
        raise AssertionError("explicit local path must replace configured SSH source")

    monkeypatch.setattr(library, "PlexImporter", FakeImporter)
    monkeypatch.setattr(discovery, "ssh_file_exists", unexpected_ssh)
    cfg = Config.model_validate({
        "database": {"path": str(tmp_path / "not-this.db")},
        "plex": {"db_ssh_target": "user@fixture:/remote", "library": "Not this library"},
    })
    before_config = cfg.model_dump()
    result = discovery.discover(
        config=cfg, musicseed_db_path=str(local), plex_db_path=str(plex),
        plex_library="Overridden library", check_server=False,
    )
    assert seen == [(plex, "Overridden library")]
    assert cfg.model_dump() == before_config
    assert not (tmp_path / "not-this.db").exists()
    assert result.can_import and result.can_recommend
    assert not result.can_write_playlists
    assert result.first_run.import_incomplete  # equal counts are not source provenance
    assert local.read_bytes() == before_content
    with closing(sqlite3.connect(local)) as conn:
        after_schema = conn.execute("SELECT sql FROM sqlite_schema ORDER BY name").fetchall()
        assert after_schema == before_schema
    assert not (tmp_path / "legacy.db-wal").exists()


def test_discovery_does_not_create_a_missing_database(tmp_path):
    local = tmp_path / "absent.db"
    result = discovery.discover(
        musicseed_db_path=str(local), check_server=False,
        config=Config.model_validate({"plex": {"db_path": str(tmp_path / "no-plex.db")}}),
    )
    assert result.first_run.db_missing
    assert not result.can_recommend
    assert not local.exists()
