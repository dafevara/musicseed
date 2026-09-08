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
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import paramiko

from musicseed.config import Config
from musicseed.exceptions import NotFoundError

SQLITE_HEADER = b"SQLite format 3\x00"
PLEX_LIBRARY_DB_NAME = "com.plexapp.plugins.library.db"
PLEX_BLOBS_DB_NAME = "com.plexapp.plugins.library.blobs.db"
_DB_NAMES = {PLEX_LIBRARY_DB_NAME, PLEX_BLOBS_DB_NAME}


@dataclass(frozen=True)
class ResolvedPlexDbs:
    """Stable local paths; an absent optional blobs database has a missing path."""

    library_db: Path
    blobs_db: Path
    source: str  # "local" | "ssh"


def parse_ssh_target(target: str) -> tuple[str | None, str, str]:
    """Split ``[user@]host:/directory``; tolerate pasted shell-escaped spaces."""
    host_spec, sep, remote_dir = target.strip().partition(":")
    if not sep or not host_spec or not remote_dir.strip("/"):
        raise NotFoundError("Invalid SSH target; expected [user@]host:/remote/directory")
    if "@" in host_spec:
        user, host = host_spec.split("@", 1)
        if not user:
            raise NotFoundError("Invalid SSH target: missing user before @")
    else:
        user, host = None, host_spec
    if not host or any(c.isspace() for c in host_spec):
        raise NotFoundError("Invalid SSH target: missing or invalid host")
    return user, host, remote_dir.rstrip("/").replace("\\ ", " ")


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


def _fetch_snapshot(config: Config, target: str, dest_dir: Path) -> None:
    """Run read-only source backups and safely unpack their SSH stream into staging."""
    user, host, remote_dir = parse_ssh_target(target)
    helper = Path(__file__).with_name("_plex_snapshot.py").read_text()
    command = shlex.join(["python3", "-c", helper, remote_dir])
    with closing(_open_ssh(
        user, host, config.plex.db_ssh_port, config.plex.db_ssh_password
    )) as client:
        stdin, stdout, stderr = client.exec_command(command, timeout=360)
        stdin.close()
        try:
            seen: set[str] = set()
            with tarfile.open(fileobj=stdout, mode="r|") as archive:
                for member in archive:
                    if member.name not in _DB_NAMES or not member.isfile() or member.name in seen:
                        raise NotFoundError("Unexpected file in remote Plex snapshot")
                    seen.add(member.name)
                    with closing(archive.extractfile(member)) as source:
                        with (dest_dir / member.name).open("xb") as dest:
                            shutil.copyfileobj(source, dest, length=1024 * 1024)
                            dest.flush()
                            os.fsync(dest.fileno())
            # Drain the small tar end padding before waiting for remote completion.
            while stdout.read(65536):
                pass
            if stdout.channel.recv_exit_status() != 0:
                raise NotFoundError("Remote SQLite backup failed")
        except (tarfile.TarError, OSError, paramiko.SSHException, NotFoundError) as exc:
            # No remote stderr is echoed: tracebacks may contain host-local paths.
            raise NotFoundError(
                "Could not create/read the remote Plex snapshot. The SSH host needs "
                "python3 with sqlite3 support, read access to the Plex files and free "
                "temporary space. Check those prerequisites and retry when Plex is idle. "
                f"({type(exc).__name__})"
            ) from exc
        finally:
            stdout.close()
            stderr.close()


def _publish_snapshot(config: Config, target: str, root: Path) -> Path:
    """Publish one complete generation, leaving prior readers and cache untouched."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix="generation-", dir=root))
    pointer = root / (stage.name + ".pointer")
    published = False
    try:
        _fetch_snapshot(config, target, stage)
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
    config: Config, *, refresh: bool = False, ssh_target: str | None = None
) -> ResolvedPlexDbs:
    """Return local files or one stable SSH snapshot generation.

    Refresh performs source-side SQLite backups over SSH and atomically replaces
    the cache pointer only after validation. Coverage never connects to SSH.
    Old generations are retained for in-flight readers; remove the source cache
    manually only when no imports/readers are active. Legacy live-copy caches
    are intentionally ignored. The optional blobs path may not exist.
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
            _publish_snapshot(config, target, root) if refresh else _cached_snapshot(root)
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
