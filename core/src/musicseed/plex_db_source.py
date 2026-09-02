"""Resolve where MusicSeed's two Plex databases come from.

MusicSeed reads two SQLite files from the Plex host: the library database
(metadata) and the blobs database (sonic vectors). Both are normally local,
but for a remote Plex server MusicSeed fetches them itself over SFTP (using
password or ``~/.ssh`` key auth) into a local cache, then reads them from
there. The recommendation runtime never touches the remote files.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import paramiko

from musicseed.config import Config
from musicseed.exceptions import NotFoundError
from musicseed.logging_config import get_logger

logger = get_logger("plex_db_source")

SQLITE_HEADER = b"SQLite format 3\x00"
PLEX_LIBRARY_DB_NAME = "com.plexapp.plugins.library.db"
PLEX_BLOBS_DB_NAME = "com.plexapp.plugins.library.blobs.db"


@dataclass(frozen=True)
class ResolvedPlexDbs:
    """Local paths to the two Plex databases, plus where they came from."""

    library_db: Path
    blobs_db: Path
    source: str  # "local" | "ssh"


def parse_ssh_target(target: str) -> tuple[str | None, str, str]:
    """Split a scp-style ``[user@]host:/remote/dir`` into ``(user, host, dir)``.

    ``user`` is ``None`` when the target omits the ``user@`` part (then the
    local username is used). Raises ``NotFoundError`` on a malformed target.
    """
    host_spec, sep, remote_dir = target.partition(":")
    if not sep or not host_spec or not remote_dir.strip("/"):
        raise NotFoundError(
            f"Invalid SSH target '{target}'; expected [user@]host:/remote/directory"
        )
    if "@" in host_spec:
        user, host = host_spec.split("@", 1)
    else:
        user, host = None, host_spec
    if not host:
        raise NotFoundError(f"Invalid SSH target '{target}'; missing host")
    remote_dir = remote_dir.rstrip("/")
    # Tolerate shell-style escaped spaces (common when pasting from a shell).
    remote_dir = remote_dir.replace("\\ ", " ")
    return user, host, remote_dir


def _cache_dir(target: str) -> Path:
    """Cache directory for one SSH target (content-addressed by the target)."""
    digest = hashlib.sha256(target.encode()).hexdigest()[:16]
    xdg = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg) if xdg else Path.home() / ".cache"
    return root / "musicseed" / "plex-dbs" / digest


def _open_ssh(
    user: str | None,
    host: str,
    port: int,
    password: str,
    timeout: float = 15.0,
) -> paramiko.SSHClient:
    """Open an SSH connection using password auth, or keys/agent when no password."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs = dict(hostname=host, port=port, username=user, timeout=timeout)
    if password:
        connect_kwargs["password"] = password
        connect_kwargs["look_for_keys"] = False
        connect_kwargs["allow_agent"] = False
    else:
        connect_kwargs["look_for_keys"] = True
        connect_kwargs["allow_agent"] = True
    client.connect(**connect_kwargs)
    return client


def _resolve_remote_dir(sftp: paramiko.SFTPClient, remote_dir: str) -> str:
    """Expand a leading ``~`` to the remote user's home directory.

    SFTP does not expand ``~`` the way a shell does, so resolve it via the
    server's realpath of the current (home) directory.
    """
    if remote_dir == "~" or remote_dir.startswith("~/"):
        home = sftp.normalize(".")
        remote_dir = home + remote_dir[1:]
    return remote_dir


def _sftp_get(
    sftp: paramiko.SFTPClient,
    remote_dir: str,
    filename: str,
    dest_dir: Path,
    *,
    required: bool,
) -> bool:
    """Download one file; return True when fetched, False when skipped."""
    dest = dest_dir / filename
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        sftp.get(f"{remote_dir}/{filename}", str(dest))
    except FileNotFoundError:
        if required:
            raise NotFoundError(f"No {filename} at {remote_dir} on the remote Plex host.")
        return False
    except (paramiko.SSHException, OSError) as e:
        if required:
            raise NotFoundError(f"Could not fetch {filename} over SFTP: {e}")
        return False
    if filename.endswith(".db") and dest.read_bytes()[: len(SQLITE_HEADER)] != SQLITE_HEADER:
        raise NotFoundError(f"{filename} fetched over SFTP is not a SQLite database.")
    return True


def ssh_file_exists(
    target: str,
    filename: str,
    *,
    password: str = "",
    port: int = 22,
    timeout: float = 10.0,
) -> tuple[bool | None, str | None]:
    """Probe whether ``filename`` exists over SSH.

    Returns ``(exists, error)``:

    - ``(True, None)`` — file present.
    - ``(False, None)`` — connected but file missing.
    - ``(None, reason)`` — connection/auth failed, with a readable reason.
    """
    user, host, remote_dir = parse_ssh_target(target)
    try:
        client = _open_ssh(user, host, port, password, timeout=timeout)
    except (paramiko.SSHException, OSError) as e:
        return None, f"{type(e).__name__}: {e}"
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = _resolve_remote_dir(sftp, remote_dir)
            sftp.stat(f"{remote_dir}/{filename}")
            return True, None
        except FileNotFoundError:
            return False, None
        finally:
            sftp.close()
    except (paramiko.SSHException, OSError) as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        client.close()


def _fetch_via_sftp(config: Config, target: str, dest_dir: Path) -> None:
    """Download the library + blobs databases (and their WAL sidecars) via SFTP."""
    user, host, remote_dir = parse_ssh_target(target)
    client = _open_ssh(
        user, host, config.plex.db_ssh_port, config.plex.db_ssh_password
    )
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = _resolve_remote_dir(sftp, remote_dir)
            for filename in (PLEX_LIBRARY_DB_NAME, PLEX_BLOBS_DB_NAME):
                _sftp_get(
                    sftp, remote_dir, filename, dest_dir,
                    required=(filename == PLEX_LIBRARY_DB_NAME),
                )
                for sidecar in ("-wal", "-shm"):
                    _sftp_get(
                        sftp, remote_dir, f"{filename}{sidecar}", dest_dir,
                        required=False,
                    )
        finally:
            sftp.close()
    finally:
        client.close()


def resolve_plex_dbs(
    config: Config, *, refresh: bool = False, ssh_target: str | None = None
) -> ResolvedPlexDbs:
    """Return local paths to the Plex library and blobs databases.

    With no ``db_ssh_target`` configured (or overridden), returns the
    configured local paths. Otherwise fetches the files over SFTP into a local
    cache, re-downloading when ``refresh`` is True (import time). When
    ``refresh`` is False and no snapshot is cached yet, raises
    ``NotFoundError`` rather than fetching.

    Args:
        config: resolved MusicSeed config.
        refresh: force a re-fetch of the remote files.
        ssh_target: per-call override for the scp target; falls back to
            ``config.plex.db_ssh_target``.

    Returns:
        The resolved local paths and the source label (``"local"`` or
        ``"ssh"``).

    Raises:
        NotFoundError: if the remote files cannot be fetched or (when not
            refreshing) have not been cached yet.
    """
    target = ssh_target or config.plex.db_ssh_target
    if not target:
        return ResolvedPlexDbs(
            library_db=config.plex.db_path_expanded,
            blobs_db=config.plex.blobs_db_path_expanded,
            source="local",
        )

    target_dir = _cache_dir(target)
    library_db = target_dir / PLEX_LIBRARY_DB_NAME
    blobs_db = target_dir / PLEX_BLOBS_DB_NAME

    if refresh:
        _fetch_via_sftp(config, target, target_dir)
    elif not library_db.exists():
        raise NotFoundError(
            f"Plex database not cached yet; run an import to fetch it from {target}"
        )

    return ResolvedPlexDbs(library_db=library_db, blobs_db=blobs_db, source="ssh")
