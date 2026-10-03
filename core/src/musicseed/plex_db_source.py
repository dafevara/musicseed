"""Resolve local Plex files or validated, atomically published SSH snapshots.

Remote imports run a standard-library Python SQLite-backup helper on the host
and stream its standalone files over SSH. Never copy live DB/WAL/SHM files.
Recommendation runtime and coverage use local data without network requests.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import tarfile
import tempfile
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import paramiko

from musicseed.config import Config
from musicseed.exceptions import NotFoundError
from musicseed.logging_config import get_logger

logger = get_logger("plex_db_source")

SQLITE_HEADER = b"SQLite format 3\x00"
PLEX_LIBRARY_DB_NAME = "com.plexapp.plugins.library.db"
PLEX_BLOBS_DB_NAME = "com.plexapp.plugins.library.blobs.db"
_DB_NAMES = {PLEX_LIBRARY_DB_NAME, PLEX_BLOBS_DB_NAME}

#: Protocol with the remote helper (``_plex_snapshot.py``): it reports failures
#: as one ``MUSICSEED_ERROR <code>`` line so the user gets an actionable message
#: instead of a traceback (which would carry host-local paths), and so nothing
#: from the remote side is echoed verbatim into the UI.
REMOTE_ERROR_PREFIX = "MUSICSEED_ERROR "
#: Progress protocol with the same helper: ``MUSICSEED_PROGRESS <done> <total>``
#: in bytes, emitted while the remote backups run (see :data:`PREPARE_PHASE`).
REMOTE_PROGRESS_PREFIX = "MUSICSEED_PROGRESS "

#: Phase reported while the SSH host builds its standalone backups. A large Plex
#: database takes minutes here and streams nothing meanwhile, so the UI needs
#: this to show movement instead of an apparently hung job.
PREPARE_PHASE = "preparing Plex snapshot"
#: Phase per database being streamed back, keyed by the archive member name.
_DOWNLOAD_PHASES = {
    PLEX_LIBRARY_DB_NAME: "downloading Plex database",
    PLEX_BLOBS_DB_NAME: "downloading Plex sonic-vector database",
}
#: Phases whose name is already user-facing (the API layer must not prefix them).
SNAPSHOT_PHASES = frozenset({PREPARE_PHASE, *_DOWNLOAD_PHASES.values()})

REMOTE_ERROR_HINTS = {
    "not_found": "Nothing exists at that path on the SSH host.",
    "not_a_directory": (
        "That SSH path is a file, not the directory holding your Plex databases. "
        "Point the target at the folder that contains "
        f"{PLEX_LIBRARY_DB_NAME}."
    ),
    "database_not_found": (
        f"That directory does not contain {PLEX_LIBRARY_DB_NAME}."
    ),
    "unreadable": (
        "The SSH user cannot read — or the host's SQLite cannot open — the Plex "
        "database. Check permissions, and that the path is Plex's Databases folder."
    ),
    "timeout": (
        "Plex's database backup took too long; retry while Plex is idle."
    ),
}
REMOTE_ERROR_FALLBACK = (
    "The remote helper failed before streaming any data. Run it by hand on the SSH "
    'host to see why: python3 -c "$(\'cat _plex_snapshot.py\')" <databases-dir>'
)


ProgressCallback = Callable[[int, int, str], None]


class _RemoteSnapshotError(NotFoundError):
    """A failure already described actionably; never re-wrapped generically."""


@dataclass(frozen=True)
class ResolvedPlexDbs:
    """Stable local paths; an absent optional blobs database has a missing path."""

    library_db: Path
    blobs_db: Path
    source: str  # "local" | "ssh"


def _strip_wrapping_quotes(value: str) -> str:
    """Drop one layer of matching shell quotes around a pasted value."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def parse_ssh_target(target: str) -> tuple[str | None, str, str]:
    r"""Split ``[user@]host:/directory`` into ``(user, host, directory)``.

    Tolerates what an ``scp``/``ssh`` command line or a copy-paste actually
    produces: shell-escaped spaces (``Application\ Support``), quotes around the
    whole target or around the remote path (``host:"~/My Plex/Databases"``), a
    trailing slash, and — because pasting the database file's own path is the
    obvious thing to do — the full path of a database *file*, in which case the
    directory that holds it is returned. That directory is what both the presence
    probe and the remote snapshot helper need.

    Raises:
        NotFoundError: when the target is not ``[user@]host:/path``.
    """
    cleaned = _strip_wrapping_quotes(target)
    host_spec, sep, remote = cleaned.partition(":")
    remote = _strip_wrapping_quotes(remote)
    if not sep or not host_spec or not remote.strip("/"):
        raise NotFoundError("Invalid SSH target; expected [user@]host:/remote/directory")
    if "@" in host_spec:
        user, host = host_spec.split("@", 1)
        if not user:
            raise NotFoundError("Invalid SSH target: missing user before @")
    else:
        user, host = None, host_spec
    if not host or any(c.isspace() for c in host_spec):
        raise NotFoundError("Invalid SSH target: missing or invalid host")
    remote_dir = remote.rstrip("/").replace("\\ ", " ")
    if remote_dir not in _DB_NAMES and Path(remote_dir).name in _DB_NAMES:
        # Pointing at com.plexapp.plugins.library.db means its parent directory.
        remote_dir = str(Path(remote_dir).parent)
    return user, host, remote_dir


def _cache_dir(target: str, port: int = 22) -> Path:
    """Versioned source identity includes port; legacy raw-copy caches are ignored."""
    identity = json.dumps([*parse_ssh_target(target), port])
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "musicseed" / "plex-dbs" / "snapshots-v1" / digest


def _open_ssh(
    user: str | None,
    host: str,
    port: int,
    password: str,
    timeout: float = 15.0,
) -> paramiko.SSHClient:
    """Connect only to a known host; never silently trust a new or changed key."""
    if not 1 <= port <= 65535:
        raise NotFoundError("SSH port must be between 1 and 65535")
    client = paramiko.SSHClient()
    try:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            hostname=host, port=port, username=user,
            password=password or None,
            look_for_keys=not bool(password), allow_agent=not bool(password),
            timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
        )
        return client
    except paramiko.BadHostKeyException as exc:
        client.close()
        raise NotFoundError(
            f"SSH host key for {host} does not match the trusted key. Verify the host "
            "fingerprint independently before changing known_hosts; never bypass a "
            "changed-host-key warning."
        ) from exc
    except paramiko.AuthenticationException as exc:
        client.close()
        raise NotFoundError(
            f"SSH authentication to {host} failed. MusicSeed connects without prompting, so "
            "it needs a key it can use in this process: load it into ssh-agent (ssh-add) and "
            "make sure whatever starts MusicSeed has SSH_AUTH_SOCK, or set "
            "plex.db_ssh_password. Keys in the default ~/.ssh locations are tried automatically."
        ) from exc
    except (paramiko.SSHException, OSError) as exc:
        client.close()
        raise NotFoundError(
            "SSH connection failed. Check host, port and authentication; verify the host "
            "fingerprint independently and establish trust with ssh before retrying. "
            "Do not bypass a changed-host-key warning."
            f" ({type(exc).__name__}: {exc})"
        ) from exc


def _resolve_remote_dir(sftp: paramiko.SFTPClient, remote_dir: str) -> str:
    """Expand ``~`` via the remote user's home, for SFTP presence probes."""
    if remote_dir == "~" or remote_dir.startswith("~/"):
        remote_dir = sftp.normalize(".") + remote_dir[1:]
    return remote_dir


def ssh_file_exists(
    target: str,
    filename: str,
    *,
    password: str = "",
    port: int = 22,
    timeout: float = 10.0,
) -> tuple[bool | None, str | None]:
    """Return presence or an actionable error; expected failures never raise."""
    try:
        user, host, remote_dir = parse_ssh_target(target)
        with closing(_open_ssh(user, host, port, password, timeout=timeout)) as client:
            with closing(client.open_sftp()) as sftp:
                remote_dir = _resolve_remote_dir(sftp, remote_dir)
                try:
                    sftp.stat(f"{remote_dir}/{filename}")
                    return True, None
                except FileNotFoundError:
                    return False, None
    except (NotFoundError, paramiko.SSHException, OSError) as exc:
        return None, str(exc)


def _validate_sqlite(path: Path, *, full: bool) -> int:
    """Validate with a bounded header read; run SQLite quick_check on new copies."""
    with path.open("rb") as file:
        if file.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
            raise NotFoundError(f"Snapshot {path.name} is not a SQLite database")
    size = path.stat().st_size
    if size < 512:
        raise NotFoundError(f"Snapshot {path.name} is truncated")
    if full:
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                page_size = conn.execute("PRAGMA page_size").fetchone()[0]
                page_count = conn.execute("PRAGMA page_count").fetchone()[0]
                if page_size * page_count != size:
                    raise NotFoundError(f"Snapshot {path.name} has an invalid page count")
                conn.execute("SELECT name FROM sqlite_schema").fetchall()
                try:
                    check = conn.execute("PRAGMA quick_check").fetchall()
                except sqlite3.OperationalError as exc:
                    # Plex databases declare custom collations ("icu_root") and FTS
                    # tokenizers ("collating") that stock SQLite cannot resolve, so
                    # quick_check cannot run on them. Never register fake comparators
                    # or tokenizers: that would claim validation we cannot perform.
                    if not str(exc).startswith((
                        "no such collation sequence:",
                        "unknown tokenizer:",
                    )):
                        raise
                else:
                    if check != [("ok",)]:
                        raise NotFoundError(f"Snapshot {path.name} failed SQLite quick_check")
        except sqlite3.Error as exc:
            raise NotFoundError(f"Snapshot {path.name} is unreadable: {exc}") from exc
    return size


def _remote_error_message(code: str) -> str:
    """Map a helper error code to a message; never echo raw remote output.

    Only the ``MUSICSEED_ERROR`` code from stderr is interpreted. Anything else
    the host wrote (tracebacks, host paths) is discarded rather than shown.
    """
    if not code:
        return ""
    return REMOTE_ERROR_HINTS.get(code, REMOTE_ERROR_FALLBACK)


def _stderr_lines(stream) -> Iterator[str]:
    """Yield text lines from a channel file, whatever mode it was opened in.

    paramiko's ``exec_command`` opens stderr with mode ``"r"`` (no ``"b"``), so
    ``readline()`` decodes to ``str`` while ``read()`` still returns ``bytes``.
    Both shapes are accepted here; the EOF check must treat ``""`` and ``b""``
    alike, because comparing against a bytes sentinel never ends for text mode.
    """
    while True:
        raw = stream.readline()
        if not raw:  # "" or b"" — end of stream
            return
        yield raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw


def _parse_progress_line(line: str) -> tuple[int, int] | None:
    """Parse ``MUSICSEED_PROGRESS <done> <total>``; ``None`` for anything else."""
    if not line.startswith(REMOTE_PROGRESS_PREFIX):
        return None
    done, _, total = line[len(REMOTE_PROGRESS_PREFIX):].partition(" ")
    if not (done.isdigit() and total.isdigit()):
        return None
    return int(done), int(total)


def _parse_error_line(line: str) -> str | None:
    """Extract the code from ``MUSICSEED_ERROR <code>``; ``None`` otherwise."""
    if not line.startswith(REMOTE_ERROR_PREFIX):
        return None
    return line[len(REMOTE_ERROR_PREFIX):].strip()


def _fetch_snapshot(
    config: Config,
    target: str,
    dest_dir: Path,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Run read-only source backups and safely unpack their SSH stream into staging.

    Progress is reported as ``(percent, 100, phase)`` so the job UI can show a
    moving bar for both halves of the wait: the host's own SQLite backups
    (:data:`PREPARE_PHASE`) and the transfer of each file
    (:data:`_DOWNLOAD_PHASES`).
    """
    user, host, remote_dir = parse_ssh_target(target)
    helper = Path(__file__).with_name("_plex_snapshot.py").read_text()
    command = shlex.join(["python3", "-c", helper, remote_dir])
    reported: dict[str, int] = {}

    def emit(done: int, total: int, phase: str) -> None:
        """Report whole-percent steps only; one job update per percent, at most."""
        percent = max(0, min(100, int(done * 100 / total) if total else 0))
        if reported.get(phase) == percent:
            return
        reported[phase] = percent
        if on_progress is not None:
            on_progress(percent, 100, phase)

    with closing(_open_ssh(
        user, host, config.plex.db_ssh_port, config.plex.db_ssh_password
    )) as client:
        stdin, stdout, stderr = client.exec_command(command, timeout=360)
        stdin.close()
        remote: dict[str, str] = {}

        def pump_stderr() -> None:
            """Drain stderr while stdout streams; the channel window is shared.

            A parse failure must never stop the drain: an unread stderr buffer
            eventually blocks the transfer on the shared channel window. Bad
            lines are logged and skipped, not fatal.
            """
            try:
                for raw in _stderr_lines(stderr):
                    line = raw.strip()
                    progress = _parse_progress_line(line)
                    if progress is not None:
                        emit(progress[0], progress[1], PREPARE_PHASE)
                        continue
                    code = _parse_error_line(line)
                    if code is not None:
                        remote["error"] = code
            except (OSError, paramiko.SSHException):
                pass  # channel closed underneath us: normal at the end
            except Exception:  # noqa: BLE001 - keep draining, log for diagnosis
                logger.warning("Plex snapshot progress reader stopped", exc_info=True)

        # Announced before the SSH round-trip so the UI moves at once; the
        # reader then takes over with the host's real numbers.
        emit(0, 1, PREPARE_PHASE)
        reader = threading.Thread(
            target=pump_stderr, name="plex-snapshot-stderr", daemon=True
        )
        reader.start()
        try:
            seen: set[str] = set()
            with tarfile.open(fileobj=stdout, mode="r|") as archive:
                for member in archive:
                    if member.name not in _DB_NAMES or not member.isfile() or member.name in seen:
                        raise NotFoundError("Unexpected file in remote Plex snapshot")
                    seen.add(member.name)
                    phase = _DOWNLOAD_PHASES[member.name]
                    emit(0, member.size, phase)
                    with closing(archive.extractfile(member)) as source:
                        copied = 0
                        with (dest_dir / member.name).open("xb") as dest:
                            while chunk := source.read(1024 * 1024):
                                dest.write(chunk)
                                copied += len(chunk)
                                emit(copied, member.size, phase)
                            dest.flush()
                            os.fsync(dest.fileno())
                        emit(copied, member.size, phase)
            # Drain the small tar end padding before waiting for remote completion.
            while stdout.read(65536):
                pass
            if stdout.channel.recv_exit_status() != 0:
                raise _RemoteSnapshotError(
                    _remote_error_message(remote.get("error", "")) or REMOTE_ERROR_FALLBACK
                )
        except _RemoteSnapshotError:
            raise
        except (tarfile.TarError, OSError, paramiko.SSHException, NotFoundError) as exc:
            # No remote stderr is echoed: tracebacks may contain host-local paths.
            raise NotFoundError(
                "Could not create/read the remote Plex snapshot. The SSH host needs "
                "python3 with sqlite3 support, read access to the Plex files and free "
                "temporary space. Check those prerequisites and retry when Plex is idle. "
                f"({type(exc).__name__})"
            ) from exc
        finally:
            reader.join(timeout=5.0)
            stdout.close()
            stderr.close()


def _publish_snapshot(
    config: Config, target: str, root: Path, on_progress: ProgressCallback | None = None
) -> Path:
    """Publish one complete generation, leaving prior readers and cache untouched."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix="generation-", dir=root))
    pointer = root / (stage.name + ".pointer")
    published = False
    try:
        _fetch_snapshot(config, target, stage, on_progress)
        sizes = {PLEX_LIBRARY_DB_NAME: _validate_sqlite(stage / PLEX_LIBRARY_DB_NAME, full=True)}
        if (stage / PLEX_BLOBS_DB_NAME).exists():
            sizes[PLEX_BLOBS_DB_NAME] = _validate_sqlite(stage / PLEX_BLOBS_DB_NAME, full=True)
        with (stage / "manifest.json").open("w") as file:
            json.dump(sizes, file)
            file.flush()
            os.fsync(file.fileno())
        with pointer.open("w") as file:
            file.write(stage.name)
            file.flush()
            os.fsync(file.fileno())
        os.replace(pointer, root / "current")
        published = True
        return stage
    finally:
        pointer.unlink(missing_ok=True)
        if not published:
            shutil.rmtree(stage)


def _cached_snapshot(root: Path) -> Path:
    """Resolve the pointer once so a concurrent refresh cannot mix generations."""
    name = (root / "current").read_text().strip()
    if not name.startswith("generation-") or Path(name).name != name:
        raise NotFoundError("Invalid Plex snapshot cache pointer; run an import to refresh")
    generation = root / name
    sizes = json.loads((generation / "manifest.json").read_text())
    if not isinstance(sizes, dict) or PLEX_LIBRARY_DB_NAME not in sizes or set(sizes) - _DB_NAMES:
        raise NotFoundError("Invalid Plex snapshot manifest; run an import to refresh")
    for filename, expected in sizes.items():
        if _validate_sqlite(generation / filename, full=False) != expected:
            raise NotFoundError("Plex snapshot cache changed; run an import to refresh")
    return generation


def resolve_plex_dbs(
    config: Config,
    *,
    refresh: bool = False,
    ssh_target: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> ResolvedPlexDbs:
    """Return local files or one stable SSH snapshot generation.

    Refresh performs source-side SQLite backups over SSH and atomically replaces
    the cache pointer only after validation. Coverage never connects to SSH.
    Old generations are retained for in-flight readers; remove the source cache
    manually only when no imports/readers are active. Legacy live-copy caches
    are intentionally ignored. The optional blobs path may not exist.

    Args:
        config: resolved MusicSeed config (SSH target and port when remote).
        refresh: fetch a new snapshot instead of reusing the published one.
        ssh_target: override the configured ``plex.db_ssh_target``.
        on_progress: optional ``(current, total, phase)`` callback. A refresh
            reports ``(percent, 100, phase)`` for :data:`PREPARE_PHASE` and each
            download phase — the only feedback available while a multi-gigabyte
            backup runs on the remote host.
    """
    target = ssh_target or config.plex.db_ssh_target
    if not target:
        return ResolvedPlexDbs(
            library_db=config.plex.db_path_expanded,
            blobs_db=config.plex.blobs_db_path_expanded,
            source="local",
        )
    try:
        root = _cache_dir(target, config.plex.db_ssh_port)
        generation = (
            _publish_snapshot(config, target, root, on_progress)
            if refresh
            else _cached_snapshot(root)
        )
    except (OSError, ValueError, paramiko.SSHException) as exc:
        raise NotFoundError(
            "Plex snapshot unavailable or invalid; run an import to refresh it. "
            "A failed refresh leaves the previous published generation untouched."
        ) from exc
    return ResolvedPlexDbs(
        library_db=generation / PLEX_LIBRARY_DB_NAME,
        blobs_db=generation / PLEX_BLOBS_DB_NAME,
        source="ssh",
    )
