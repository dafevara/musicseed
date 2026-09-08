"""Offline SSH snapshot tests with real SQLite files, never a live Plex host."""

import io
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import musicseed.plex_db_source as pds
import paramiko
import pytest
from musicseed.config import Config
from musicseed.exceptions import NotFoundError


def _config(tmp_path, target="user@nas:/Plex/Databases"):
    return Config.model_validate({
        "database": {"path": str(tmp_path / "musicseed.db")},
        "plex": {"db_path": str(tmp_path / "local.db"), "db_ssh_target": target},
    })


def _database(path, value=1):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE fixture(value INTEGER)")
        conn.execute("INSERT INTO fixture VALUES (?)", (value,))
    return path.read_bytes()


def _archive(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    return buffer.getvalue()


class _Stdout(io.BytesIO):
    @property
    def channel(self):
        return self

    def recv_exit_status(self):
        return 0


class _Client:
    def __init__(self, archive):
        self.archive = archive
        self.commands = []
        self.closed = False

    def exec_command(self, command, **kwargs):
        self.commands.append(command)
        return io.BytesIO(), _Stdout(self.archive), io.BytesIO()

    def close(self):
        self.closed = True


@pytest.fixture
def remote(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _database(tmp_path / "fixture.db")
    client = _Client(_archive({pds.PLEX_LIBRARY_DB_NAME: data, pds.PLEX_BLOBS_DB_NAME: data}))
    monkeypatch.setattr(pds, "_open_ssh", lambda *a, **k: client)
    return client


def test_parse_ssh_target():
    assert pds.parse_ssh_target("u@nas:/a\\ b/") == ("u", "nas", "/a b")
    assert pds.parse_ssh_target("nas:~/Plex") == (None, "nas", "~/Plex")
    for bad in ("missing-colon", "@nas:/db", "nas:", "bad host:/db"):
        with pytest.raises(NotFoundError):
            pds.parse_ssh_target(bad)


def test_local_passthrough(tmp_path):
    cfg = _config(tmp_path, target="")
    result = pds.resolve_plex_dbs(cfg)
    assert result.source == "local"
    assert result.library_db == cfg.plex.db_path_expanded
    assert result.blobs_db == cfg.plex.blobs_db_path_expanded


def test_cache_identity_includes_port_and_ignores_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert pds._cache_dir("nas:/db", 22) != pds._cache_dir("nas:/db", 2222)
    assert pds._cache_dir("nas:/a\\ b/", 22) == pds._cache_dir("nas:/a b", 22)
    root = pds._cache_dir("nas:/db")
    root.mkdir(parents=True)
    (root / pds.PLEX_LIBRARY_DB_NAME).write_bytes(_database(tmp_path / "old.db"))
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(_config(tmp_path, "nas:/db"))


def test_snapshot_is_readable_and_cached_without_network(remote, tmp_path):
    cfg = _config(tmp_path)
    result = pds.resolve_plex_dbs(cfg, refresh=True)
    assert result.source == "ssh"
    assert remote.closed
    with sqlite3.connect(result.library_db) as conn:
        assert conn.execute("SELECT value FROM fixture").fetchone() == (1,)
    assert pds.resolve_plex_dbs(cfg) == result
    assert len(remote.commands) == 1
    assert not list(result.library_db.parent.glob("*-wal"))
    # Paths are shell arguments, never interpolated into the helper's code.
    args = shlex.split(remote.commands[0])
    assert args[:2] == ["python3", "-c"]
    assert args[-1] == "/Plex/Databases"


def test_override_and_shell_metacharacters_are_literal(remote, tmp_path):
    target = "nas:~/Plex's files; echo nope"
    pds.resolve_plex_dbs(_config(tmp_path, ""), refresh=True, ssh_target=target)
    assert shlex.split(remote.commands[0])[-1] == "~/Plex's files; echo nope"


@pytest.mark.parametrize("failure", ["truncated-stream", "invalid-sqlite", "missing-library"])
def test_failed_refresh_preserves_last_good_generation(remote, tmp_path, failure):
    cfg = _config(tmp_path)
    good = pds.resolve_plex_dbs(cfg, refresh=True)
    before = good.library_db.read_bytes()
    if failure == "truncated-stream":
        remote.archive = remote.archive[:600]
    elif failure == "invalid-sqlite":
        remote.archive = _archive({pds.PLEX_LIBRARY_DB_NAME: pds.SQLITE_HEADER + b"bad"})
    else:
        remote.archive = _archive({})
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg, refresh=True)
    assert pds.resolve_plex_dbs(cfg) == good
    assert good.library_db.read_bytes() == before
    assert list(good.library_db.parent.parent.glob("generation-*")) == [good.library_db.parent]


def test_optional_blobs_disappearance_does_not_reuse_old_file(remote, tmp_path):
    cfg = _config(tmp_path)
    old = pds.resolve_plex_dbs(cfg, refresh=True)
    remote.archive = _archive({pds.PLEX_LIBRARY_DB_NAME: old.library_db.read_bytes()})
    new = pds.resolve_plex_dbs(cfg, refresh=True)
    assert new.library_db.parent != old.library_db.parent
    assert not new.blobs_db.exists()
    assert old.blobs_db.exists()  # prior readers retain stable paths
    assert pds.resolve_plex_dbs(cfg) == new


def test_corrupted_cache_is_not_accepted(remote, tmp_path):
    cfg = _config(tmp_path)
    result = pds.resolve_plex_dbs(cfg, refresh=True)
    result.library_db.write_bytes(pds.SQLITE_HEADER)
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg)


@pytest.mark.parametrize("name", ["../escape", "/escape", pds.PLEX_LIBRARY_DB_NAME + "-wal"])
def test_unexpected_archive_members_rejected(remote, tmp_path, name):
    remote.archive = _archive({name: b"bad"})
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(_config(tmp_path), refresh=True)
    assert not (tmp_path / "escape").exists()


def test_nonzero_remote_exit_rejects_even_valid_archive(remote, tmp_path, monkeypatch):
    monkeypatch.setattr(_Stdout, "recv_exit_status", lambda self: 1)
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(_config(tmp_path), refresh=True)


def test_remote_helper_backs_up_committed_wal_and_cleans_temp(tmp_path):
    source = tmp_path / "source with ' spaces"
    source.mkdir()
    remote_tmp = tmp_path / "remote-temp"
    remote_tmp.mkdir()
    db = sqlite3.connect(source / pds.PLEX_LIBRARY_DB_NAME)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE fixture(value INTEGER)")
        db.execute("INSERT INTO fixture VALUES (42)")
        db.commit()
        before = (source / pds.PLEX_LIBRARY_DB_NAME).read_bytes()
        helper = Path(pds.__file__).with_name("_plex_snapshot.py").read_text()
        result = subprocess.run(
            [sys.executable, "-c", helper, str(source)],
            env={**os.environ, "TMPDIR": str(remote_tmp)},
            capture_output=True, check=True, timeout=10,
        )
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            assert archive.getnames() == [pds.PLEX_LIBRARY_DB_NAME]
            output = tmp_path / "backup.db"
            output.write_bytes(archive.extractfile(pds.PLEX_LIBRARY_DB_NAME).read())
        with sqlite3.connect(output) as backup:
            assert backup.execute("SELECT value FROM fixture").fetchone() == (42,)
            assert backup.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert (source / pds.PLEX_LIBRARY_DB_NAME).read_bytes() == before
        assert not list(remote_tmp.iterdir())
    finally:
        db.close()


@pytest.mark.parametrize("password", ["", "test password"])
def test_ssh_loads_known_hosts_rejects_unknown_and_preserves_auth(monkeypatch, password):
    from unittest.mock import MagicMock

    client = MagicMock()
    monkeypatch.setattr(pds.paramiko, "SSHClient", lambda: client)
    assert pds._open_ssh("user", "nas", 2222, password) is client
    client.load_system_host_keys.assert_called_once_with()
    policy = client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.RejectPolicy)
    key = MagicMock()
    key.get_fingerprint.return_value = b"fixture fingerprint"
    with pytest.raises(paramiko.SSHException):
        policy.missing_host_key(client, "unknown", key)
    kwargs = client.connect.call_args.kwargs
    assert kwargs["port"] == 2222
    assert kwargs["password"] == (password or None)
    assert kwargs["allow_agent"] is (not bool(password))
    assert kwargs["look_for_keys"] is (not bool(password))


def test_changed_host_key_failure_closes_connection(monkeypatch):
    from unittest.mock import MagicMock

    client = MagicMock()
    key = MagicMock()
    client.connect.side_effect = paramiko.BadHostKeyException("nas", key, key)
    monkeypatch.setattr(pds.paramiko, "SSHClient", lambda: client)
    with pytest.raises(NotFoundError, match="changed-host-key"):
        pds._open_ssh("u", "nas", 22, "")
    client.close.assert_called_once()


def test_probe_returns_expected_errors_without_raising(monkeypatch):
    assert pds.ssh_file_exists("bad", "file.db")[0] is None

    def fail(*args, **kwargs):
        raise NotFoundError("untrusted SSH key")

    monkeypatch.setattr(pds, "_open_ssh", fail)
    assert pds.ssh_file_exists("u@h:/d", "file.db") == (None, "untrusted SSH key")


def test_probe_expands_tilde(monkeypatch):
    from unittest.mock import MagicMock

    client = MagicMock()
    sftp = client.open_sftp.return_value
    sftp.normalize.return_value = "/home/u"
    monkeypatch.setattr(pds, "_open_ssh", lambda *a, **k: client)
    assert pds.ssh_file_exists("u@h:~/Library/App Support", "file.db") == (True, None)
    sftp.stat.assert_called_once_with("/home/u/Library/App Support/file.db")
    sftp.close.assert_called_once()
    client.close.assert_called_once()
    sftp.stat.side_effect = FileNotFoundError()
    assert pds.ssh_file_exists("u@h:/d", "file.db") == (False, None)


def test_valid_plex_custom_collation_is_not_replaced_or_rejected(remote, tmp_path):
    path = tmp_path / "custom.db"
    with sqlite3.connect(path) as db:
        db.create_collation("plex_fixture", lambda a, b: (a > b) - (a < b))
        db.execute("CREATE TABLE metadata(name TEXT COLLATE plex_fixture)")
        db.execute("CREATE INDEX ix_metadata ON metadata(name)")
        db.execute("INSERT INTO metadata VALUES ('fixture')")
    remote.archive = _archive({pds.PLEX_LIBRARY_DB_NAME: path.read_bytes()})
    result = pds.resolve_plex_dbs(_config(tmp_path), refresh=True)
    with sqlite3.connect(result.library_db) as db:
        assert db.execute("SELECT name FROM metadata").fetchone() == ("fixture",)


def test_publication_failure_preserves_previous_pointer(remote, tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    good = pds.resolve_plex_dbs(cfg, refresh=True)

    def fail(*args):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(pds.os, "replace", fail)
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg, refresh=True)
    assert pds.resolve_plex_dbs(cfg) == good
    assert list(good.library_db.parent.parent.glob("generation-*")) == [good.library_db.parent]


def test_archive_symlinks_rejected(remote, tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        member = tarfile.TarInfo(pds.PLEX_LIBRARY_DB_NAME)
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    remote.archive = buffer.getvalue()
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(_config(tmp_path), refresh=True)


def test_concurrent_publications_keep_each_readers_generation(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    barrier = Barrier(2)
    payload = _database(tmp_path / "payload.db")

    def fetch(config, target, stage):
        (stage / pds.PLEX_LIBRARY_DB_NAME).write_bytes(payload)
        barrier.wait(timeout=5)

    monkeypatch.setattr(pds, "_fetch_snapshot", fetch)
    cfg = _config(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(pds.resolve_plex_dbs, cfg, refresh=True) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0].library_db != results[1].library_db
    assert all(r.library_db.read_bytes() == payload for r in results)
    assert pds.resolve_plex_dbs(cfg) in results


def test_manifest_invalid_pointer_rejected(remote, tmp_path):
    cfg = _config(tmp_path)
    good = pds.resolve_plex_dbs(cfg, refresh=True)
    root = good.library_db.parent.parent
    (root / "current").write_text("../outside")
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg)
    (root / "current").write_text(good.library_db.parent.name)
    (good.library_db.parent / "manifest.json").write_text(json.dumps([]))
    with pytest.raises(NotFoundError):
        pds.resolve_plex_dbs(cfg)
