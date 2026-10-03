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


# The exact shape pasted from an `scp` command line, with escaped spaces.
PASTED_DB_FILE = (
    r"dafevara@caladan.tail0c115.ts.net:~/Library/Application\ Support/"
    r"Plex\ Media\ Server/Plug-in\ Support/Databases/" + pds.PLEX_LIBRARY_DB_NAME
)
_MAILBOX = (
    "dafevara",
    "caladan.tail0c115.ts.net",
    "~/Library/Application Support/Plex Media Server/Plug-in Support/Databases",
)


@pytest.mark.parametrize(
    "target",
    [
        PASTED_DB_FILE,
        'dafevara@caladan.tail0c115.ts.net:"~/Library/Application Support/Plex Media '
        'Server/Plug-in Support/Databases/"',
        "dafevara@caladan.tail0c115.ts.net:~/Library/Application Support/Plex Media "
        "Server/Plug-in Support/Databases",
        r"dafevara@caladan.tail0c115.ts.net:~/Library/Application\ Support/Plex\ Media\ "
        r"Server/Plug-in\ Support/Databases/com.plexapp.plugins.library.blobs.db",
    ],
)
def test_parse_ssh_target_normalizes_real_pastes(target):
    """A pasted database *file* means the directory that holds it.

    Regression: the file name used to be kept, so the probe and the snapshot
    helper looked for ``<file>/com.plexapp.plugins.library.db`` and failed with
    "unable to open database file" while ``scp`` with the same path worked.
    """
    assert pds.parse_ssh_target(target) == _MAILBOX
    # Every spelling of the same source must share one snapshot cache.
    canonical = f"{_MAILBOX[0]}@{_MAILBOX[1]}:{_MAILBOX[2]}"
    assert pds._cache_dir(target) == pds._cache_dir(canonical)


def test_parse_ssh_target_keeps_an_unrelated_file_path():
    # Only a Plex database name implies "use my parent directory"; anything else
    # is passed through so the remote helper can report what is wrong.
    user, host, remote = pds.parse_ssh_target("u@nas:/Plex/Databases/library.db")
    assert (user, host, remote) == ("u", "nas", "/Plex/Databases/library.db")


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


def test_remote_error_code_becomes_an_actionable_message(
    remote, tmp_path, monkeypatch
):
    """The helper's code is shown; its traceback never is."""
    monkeypatch.setattr(_Stdout, "recv_exit_status", lambda self: 1)
    monkeypatch.setattr(
        _Client,
        "exec_command",
        lambda self, command, **kwargs: (
            io.BytesIO(),
            _Stdout(self.archive),
            io.BytesIO(
                b"Traceback (most recent call last):\n"
                b"  File \"/Users/dafevara/Library/.../plex_db_source.py\", line 36\n"
                b"MUSICSEED_ERROR database_not_found\n"
            ),
        ),
    )

    with pytest.raises(NotFoundError) as excinfo:
        pds.resolve_plex_dbs(_config(tmp_path), refresh=True)

    message = str(excinfo.value)
    assert pds.PLEX_LIBRARY_DB_NAME in message
    assert "does not contain" in message
    # Host-local paths and tracebacks stay on the host.
    assert "Traceback" not in message
    assert "dafevara" not in message
    assert "Could not create/read the remote Plex snapshot" not in message


def test_unknown_remote_error_code_falls_back_without_echoing_stderr(
    remote, tmp_path, monkeypatch
):
    monkeypatch.setattr(_Stdout, "recv_exit_status", lambda self: 1)
    monkeypatch.setattr(
        _Client,
        "exec_command",
        lambda self, command, **kwargs: (
            io.BytesIO(),
            _Stdout(self.archive),
            io.BytesIO(b"MUSICSEED_ERROR something_new\n/secret/path\n"),
        ),
    )

    with pytest.raises(NotFoundError) as excinfo:
        pds.resolve_plex_dbs(_config(tmp_path), refresh=True)

    message = str(excinfo.value)
    assert message == pds.REMOTE_ERROR_FALLBACK
    assert "/secret/path" not in message


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("not_found", "Nothing exists at that path"),
        ("not_a_directory", "is a file, not the directory"),
        ("database_not_found", "does not contain"),
        ("unreadable", "cannot read"),
        ("timeout", "took too long"),
    ],
)
def test_remote_error_hints_cover_every_helper_code(code, expected):
    assert expected in pds.REMOTE_ERROR_HINTS[code]
    assert code in Path(pds.__file__).with_name("_plex_snapshot.py").read_text()


def test_remote_error_ignores_output_without_a_code():
    assert pds._remote_error_message("") == ""
    assert (
        pds._remote_error_message("not_a_directory")
        == pds.REMOTE_ERROR_HINTS["not_a_directory"]
    )
    assert pds._remote_error_message("brand_new_code") == pds.REMOTE_ERROR_FALLBACK


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


def test_remote_helper_accepts_a_database_file_path(tmp_path):
    """Pasting the database file must work exactly like naming its directory."""
    source = tmp_path / "Databases"
    source.mkdir()
    _database(source / pds.PLEX_LIBRARY_DB_NAME)
    helper = Path(pds.__file__).with_name("_plex_snapshot.py").read_text()

    result = subprocess.run(
        [sys.executable, "-c", helper, str(source / pds.PLEX_LIBRARY_DB_NAME)],
        capture_output=True, check=True, timeout=10,
    )

    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        assert archive.getnames() == [pds.PLEX_LIBRARY_DB_NAME]


@pytest.mark.parametrize(
    ("relative", "code"),
    [
        ("missing-dir", "not_found"),
        ("not-a-databases-dir/notes.txt", "not_a_directory"),
        ("empty-dir", "database_not_found"),
    ],
)
def test_remote_helper_reports_a_code_not_a_traceback(tmp_path, relative, code):
    """The UI gets a precise reason instead of "unable to open database file"."""
    if relative.startswith("not-a-databases-dir"):
        bad = tmp_path / "not-a-databases-dir"
        bad.mkdir()
        (bad / "notes.txt").write_text("not a database")
    elif relative == "empty-dir":
        (tmp_path / "empty-dir").mkdir()
    helper = Path(pds.__file__).with_name("_plex_snapshot.py").read_text()

    result = subprocess.run(
        [sys.executable, "-c", helper, str(tmp_path / relative)],
        capture_output=True, timeout=10,
    )

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.decode().strip() == f"{pds.REMOTE_ERROR_PREFIX}{code}"
    assert code in pds.REMOTE_ERROR_HINTS


def test_remote_helper_reports_an_unreadable_database(tmp_path):
    source = tmp_path / "Databases"
    source.mkdir()
    (source / pds.PLEX_LIBRARY_DB_NAME).write_bytes(b"definitely not sqlite")
    helper = Path(pds.__file__).with_name("_plex_snapshot.py").read_text()

    result = subprocess.run(
        [sys.executable, "-c", helper, str(source)], capture_output=True, timeout=10,
    )

    assert result.returncode == 1
    # Progress lines may precede the failure; the code is the last line.
    lines = result.stderr.decode().strip().splitlines()
    assert lines[-1] == f"{pds.REMOTE_ERROR_PREFIX}unreadable"
    assert all(line.startswith(pds.REMOTE_PROGRESS_PREFIX) for line in lines[:-1])


def test_remote_helper_usage_code():
    helper = Path(pds.__file__).with_name("_plex_snapshot.py").read_text()
    result = subprocess.run(
        [sys.executable, "-c", helper], capture_output=True, timeout=10,
    )
    assert result.returncode == 1
    assert result.stderr.decode().strip() == f"{pds.REMOTE_ERROR_PREFIX}usage"


def test_remote_helper_reports_backup_progress(tmp_path):
    """A remote backup of a large database must not look hung.

    The host streams nothing on stdout until every backup is done, so progress
    lines on stderr are the only feedback during that window.
    """
    source = tmp_path / "Databases"
    source.mkdir()
    _database(source / pds.PLEX_LIBRARY_DB_NAME)
    _database(source / pds.PLEX_BLOBS_DB_NAME, value=2)
    total = (source / pds.PLEX_LIBRARY_DB_NAME).stat().st_size + (
        source / pds.PLEX_BLOBS_DB_NAME
    ).stat().st_size
    helper = Path(pds.__file__).with_name("_plex_snapshot.py").read_text()

    result = subprocess.run(
        [sys.executable, "-c", helper, str(source)], capture_output=True, check=True, timeout=20,
    )

    lines = result.stderr.decode().strip().splitlines()
    assert lines, "the helper must report progress"
    samples = []
    for line in lines:
        assert line.startswith(pds.REMOTE_PROGRESS_PREFIX), line
        done, _, reported_total = line[len(pds.REMOTE_PROGRESS_PREFIX):].partition(" ")
        assert int(reported_total) == total
        samples.append(int(done))
    assert samples == sorted(samples)  # never goes backwards
    assert samples[0] == 0
    assert samples[-1] == total  # both databases accounted for
    # One line per percent at most, however many pages SQLite reports.
    assert len(samples) <= 101


def test_fetch_reports_prepare_and_download_progress(remote, tmp_path, monkeypatch):
    """The job gets a moving bar for both halves of the wait."""
    monkeypatch.setattr(_Stdout, "recv_exit_status", lambda self: 0)
    size = (tmp_path / "fixture.db").stat().st_size  # the archived payload
    monkeypatch.setattr(
        _Client,
        "exec_command",
        lambda self, command, **kwargs: (
            io.BytesIO(),
            _Stdout(self.archive),
            io.BytesIO(
                f"{pds.REMOTE_PROGRESS_PREFIX}0 {size}\n"
                f"{pds.REMOTE_PROGRESS_PREFIX}{size // 2} {size}\n"
                f"{pds.REMOTE_PROGRESS_PREFIX}{size} {size}\n".encode()
            ),
        ),
    )
    seen: list[tuple[int, int, str]] = []

    pds.resolve_plex_dbs(_config(tmp_path), refresh=True, on_progress=lambda *a: seen.append(a))

    prepare = [p for p in seen if p[2] == pds.PREPARE_PHASE]
    assert [p[0] for p in prepare] == [0, 50, 100]
    assert all(p[1] == 100 for p in seen)  # reported as percent, not raw bytes

    library = [p for p in seen if p[2] == "downloading Plex database"]
    assert library[0][0] == 0
    assert library[-1][0] == 100
    assert [p[0] for p in library] == sorted(p[0] for p in library)
    assert "downloading Plex sonic-vector database" in {p[2] for p in seen}


class _StderrChannel:
    """Minimal channel backing a real paramiko stderr file, over memory."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._buffer = io.BytesIO(payload)

    def recv_stderr(self, size):
        return self._buffer.read(size)

    def recv(self, size):
        return b""

    def sendall(self, data):
        return None

    def close(self):
        pass

    @property
    def remaining(self) -> int:
        return len(self._payload) - self._buffer.tell()


def text_stderr(payload: bytes) -> paramiko.channel.ChannelStderrFile:
    """A real paramiko stderr file over ``payload``, in the mode production uses.

    ``exec_command`` opens stderr as ``makefile_stderr("r")`` — text mode — so
    ``readline()`` returns ``str`` while ``read()`` returns ``bytes``. Using
    paramiko's own class reproduces that instead of inventing a test double.
    """
    return paramiko.channel.ChannelStderrFile(_StderrChannel(payload))


class _TextClient(_Client):
    """Client whose stderr is a real paramiko text-mode channel file."""

    def __init__(self, archive, stderr: bytes | str, exit_status: int = 0):
        super().__init__(archive)
        payload = stderr.encode() if isinstance(stderr, str) else stderr
        self.stderr = text_stderr(payload)
        self.exit_status = exit_status

    def exec_command(self, command, **kwargs):
        self.commands.append(command)
        stdout = _Stdout(self.archive)
        stdout.recv_exit_status = lambda: self.exit_status
        return io.BytesIO(), stdout, self.stderr


def test_stderr_lines_handles_text_and_binary_streams():
    """Normalize both shapes and, critically, stop at EOF in either one.

    A bytes sentinel would never match paramiko's text-mode ``""``, leaving the
    reader spinning forever while the transfer stalled on a full channel window.
    """
    assert list(pds._stderr_lines(io.StringIO("a\nb\n"))) == ["a\n", "b\n"]
    assert list(pds._stderr_lines(io.BytesIO(b"a\nb\n"))) == ["a\n", "b\n"]
    assert list(pds._stderr_lines(io.StringIO(""))) == []
    assert list(pds._stderr_lines(io.BytesIO(b""))) == []
    # Unterminated final lines still arrive from both shapes.
    assert list(pds._stderr_lines(io.StringIO("tail"))) == ["tail"]
    assert list(pds._stderr_lines(io.BytesIO(b"tail"))) == ["tail"]
    # The real paramiko file object behaves the same way.
    real = text_stderr(b"MUSICSEED_PROGRESS 1 2\ntail")
    assert isinstance(real.readline(), str)
    assert list(pds._stderr_lines(text_stderr(b"a\ntail"))) == ["a\n", "tail"]


def test_progress_and_error_line_parsing():
    assert pds._parse_progress_line("MUSICSEED_PROGRESS 12 34") == (12, 34)
    for rejected in (
        "MUSICSEED_ERROR not_found",
        "MUSICSEED_PROGRESS",
        "MUSICSEED_PROGRESS a b",
        "MUSICSEED_PROGRESS 12",
        "Traceback (most recent call last):",
        "",
    ):
        assert pds._parse_progress_line(rejected) is None

    assert pds._parse_error_line("MUSICSEED_ERROR not_found") == "not_found"
    assert pds._parse_error_line("MUSICSEED_PROGRESS 1 2") is None
    assert pds._parse_error_line("/home/user/secret/path") is None


def test_a_bad_stderr_line_does_not_stop_the_drain(tmp_path, monkeypatch):
    """Unparsable output is skipped: an undrained buffer would block the transfer."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _database(tmp_path / "fixture.db")
    size = len(data)
    client = _TextClient(
        _archive({pds.PLEX_LIBRARY_DB_NAME: data}),
        (
            "not a protocol line\n"
            "MUSICSEED_PROGRESS nonsense\n"
            f"{pds.REMOTE_PROGRESS_PREFIX}{size} {size}\n"
        ),
    )
    monkeypatch.setattr(pds, "_open_ssh", lambda *a, **k: client)
    seen: list[tuple[int, int, str]] = []

    pds.resolve_plex_dbs(_config(tmp_path), refresh=True, on_progress=lambda *a: seen.append(a))

    # The good line still landed and the stream was read to EOF.
    assert (100, 100, pds.PREPARE_PHASE) in seen
    assert client.stderr.channel.remaining == 0


def test_fetch_reads_progress_from_a_text_mode_stderr(tmp_path, monkeypatch):
    """Regression: paramiko stderr is str-mode; the reader thread must cope."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _database(tmp_path / "fixture.db")
    size = len(data)
    client = _TextClient(
        _archive({pds.PLEX_LIBRARY_DB_NAME: data}),
        (
            f"{pds.REMOTE_PROGRESS_PREFIX}0 {size}\n"
            f"{pds.REMOTE_PROGRESS_PREFIX}{size // 4} {size}\n"
            f"{pds.REMOTE_PROGRESS_PREFIX}{size} {size}\n"
        ),
    )
    monkeypatch.setattr(pds, "_open_ssh", lambda *a, **k: client)
    seen: list[tuple[int, int, str]] = []

    pds.resolve_plex_dbs(_config(tmp_path), refresh=True, on_progress=lambda *a: seen.append(a))

    assert [p[0] for p in seen if p[2] == pds.PREPARE_PHASE] == [0, 25, 100]
    assert client.stderr.channel.remaining == 0  # drained, reader stopped at EOF


def test_fetch_maps_errors_from_a_text_mode_stderr(tmp_path, monkeypatch):
    """The error code survives the text-mode stream too."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    data = _database(tmp_path / "fixture.db")
    client = _TextClient(
        _archive({pds.PLEX_LIBRARY_DB_NAME: data}),
        f"{pds.REMOTE_ERROR_PREFIX}database_not_found\n",
        exit_status=1,
    )
    monkeypatch.setattr(pds, "_open_ssh", lambda *a, **k: client)

    with pytest.raises(NotFoundError) as excinfo:
        pds.resolve_plex_dbs(_config(tmp_path), refresh=True)

    assert pds.PLEX_LIBRARY_DB_NAME in str(excinfo.value)


def test_progress_is_optional(remote, tmp_path):
    """Callers without a progress callback (coverage, CLI) stay unchanged."""
    result = pds.resolve_plex_dbs(_config(tmp_path), refresh=True)
    assert result.library_db.exists()


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


def test_authentication_failure_says_what_to_fix(monkeypatch):
    """An agent-based login that only works in a terminal must be explained.

    paramiko never prompts: a key loaded in the user's shell agent is invisible
    to a MusicSeed process without SSH_AUTH_SOCK, which looks like "scp works
    but the web UI cannot connect".
    """
    from unittest.mock import MagicMock

    client = MagicMock()
    client.connect.side_effect = paramiko.AuthenticationException("Authentication failed.")
    monkeypatch.setattr(pds.paramiko, "SSHClient", lambda: client)

    with pytest.raises(NotFoundError) as excinfo:
        pds._open_ssh("u", "nas", 22, "")

    message = str(excinfo.value)
    assert "SSH authentication to nas failed" in message
    assert "ssh-agent" in message
    assert "SSH_AUTH_SOCK" in message
    assert "plex.db_ssh_password" in message
    client.close.assert_called_once()


def test_unreachable_host_reports_the_generic_ssh_failure(monkeypatch):
    from unittest.mock import MagicMock

    client = MagicMock()
    client.connect.side_effect = OSError("Network is unreachable")
    monkeypatch.setattr(pds.paramiko, "SSHClient", lambda: client)

    with pytest.raises(NotFoundError, match="SSH connection failed"):
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


def test_plex_custom_fts_tokenizer_is_tolerated(remote, tmp_path):
    path = tmp_path / "fts.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE metadata(value INTEGER)")
        db.execute("INSERT INTO metadata VALUES (1)")
        # Plex declares fts4 tables with a custom "collating" tokenizer registered
        # by its own SQLite runtime; inject the schema row without creating the vtab.
        db.execute("PRAGMA writable_schema=ON")
        db.execute(
            "INSERT INTO sqlite_schema(type, name, tbl_name, rootpage, sql) "
            "VALUES('table', 'fts4_fixture', 'fts4_fixture', 0, "
            "\"CREATE VIRTUAL TABLE fts4_fixture USING fts4("
            "content='metadata', tokenize=collating "
            "'root@colStrength=primary;colAlternate=shifted')\")"
        )
    remote.archive = _archive({pds.PLEX_LIBRARY_DB_NAME: path.read_bytes()})
    result = pds.resolve_plex_dbs(_config(tmp_path), refresh=True)
    with sqlite3.connect(result.library_db) as db:
        assert db.execute("SELECT value FROM metadata").fetchone() == (1,)


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

    def fetch(config, target, stage, on_progress=None):
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
