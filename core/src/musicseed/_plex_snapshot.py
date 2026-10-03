"""Standalone remote helper: stream consistent Plex SQLite backups over stdout.

Executed through ``python3 -c`` on the SSH host; use only the Python standard
library, not MusicSeed imports. Each database is backed up independently.

Two stderr protocols keep the caller informed without echoing host details:

* ``MUSICSEED_PROGRESS <done_bytes> <total_bytes>`` — coarse progress while the
  remote SQLite backups run. For a multi-gigabyte library this phase takes
  minutes and produces no stdout, so without it the UI looks hung.
* ``MUSICSEED_ERROR <code>`` — one machine-readable failure code instead of a
  traceback (a traceback would leak host-local paths into the UI). Codes in use:
  ``not_found``, ``not_a_directory``, ``database_not_found``, ``unreadable``,
  ``timeout``, ``usage``, ``other``.
"""

import sqlite3
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from pathlib import Path

NAMES = ("com.plexapp.plugins.library.db", "com.plexapp.plugins.library.blobs.db")

#: Keep in sync with ``musicseed.plex_db_source.REMOTE_ERROR_PREFIX``.
ERROR_PREFIX = "MUSICSEED_ERROR "
#: Keep in sync with ``musicseed.plex_db_source.REMOTE_PROGRESS_PREFIX``.
PROGRESS_PREFIX = "MUSICSEED_PROGRESS "


class SnapshotError(Exception):
    """A failure with a code the caller turns into an actionable message."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def report(code):
    """Write one machine-readable code to stderr and return an exit status."""
    print(f"{ERROR_PREFIX}{code}", file=sys.stderr, flush=True)
    return 1


def _reporter(stderr, total_bytes):
    """Return a callback reporting whole-backup progress at one step per percent.

    Percent is measured in bytes across every database so the caller sees one
    smooth run (library first, then blobs) rather than two restarts.
    """
    state = {"percent": -1}

    def report(done_bytes):
        percent = int(done_bytes * 100 / total_bytes) if total_bytes else 100
        percent = max(0, min(100, percent))
        if percent == state["percent"]:
            return
        state["percent"] = percent
        print(f"{PROGRESS_PREFIX}{done_bytes} {total_bytes}", file=stderr, flush=True)

    return report


def stream_snapshot(directory, output, stderr=None):
    """Back up read-only source connections, then stream standalone files.

    ``directory`` is the Plex ``Databases`` folder. The path to a database file
    is accepted too (its parent is used) because that is what people paste.
    """
    stderr = stderr if stderr is not None else sys.stderr
    source_dir = Path(directory).expanduser()
    if not source_dir.exists():
        raise SnapshotError("not_found")
    if not source_dir.is_dir():
        # The path to a database file is accepted (they get pasted constantly);
        # any other file is not a Databases directory in disguise.
        if source_dir.name not in NAMES:
            raise SnapshotError("not_a_directory")
        source_dir = source_dir.parent
    source_dir = source_dir.resolve()

    if not (source_dir / NAMES[0]).is_file():
        raise SnapshotError("database_not_found")

    present = [name for name in NAMES if (source_dir / name).is_file()]
    total_bytes = sum((source_dir / name).stat().st_size for name in present)
    report = _reporter(stderr, total_bytes)
    report(0)

    with tempfile.TemporaryDirectory(prefix="musicseed-snapshot-") as temp:
        files = []
        completed_bytes = 0
        for name in present:
            source = source_dir / name
            size = source.stat().st_size
            destination = Path(temp) / name
            deadline = time.monotonic() + 300

            def progress(status, remaining, total, base=completed_bytes, size=size):
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        "SQLite backup exceeded five minutes; retry when Plex is idle"
                    )
                done_pages = (total - remaining) if total else 0
                report(base + (size * done_pages // total if total else 0))

            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
                with closing(sqlite3.connect(destination)) as dst:
                    # Backup includes committed WAL pages without copying live sidecars.
                    # Unlike VACUUM, it does not rebuild Plex's custom indexes/collations.
                    src.backup(dst, pages=1024, progress=progress)
                    dst.execute("PRAGMA journal_mode=DELETE")
            files.append(destination)
            completed_bytes += size
            report(completed_bytes)

        with tarfile.open(fileobj=output, mode="w|") as archive:
            for path in files:
                archive.add(path, arcname=path.name, recursive=False)


def main(argv):
    """Run the helper for one argument; return a process exit status."""
    if len(argv) != 2:
        return report("usage")
    try:
        stream_snapshot(argv[1], sys.stdout.buffer)
    except SnapshotError as exc:
        return report(exc.code)
    except sqlite3.Error:
        return report("unreadable")
    except TimeoutError:
        return report("timeout")
    except Exception:  # noqa: BLE001 - report a code, never a traceback
        return report("other")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
