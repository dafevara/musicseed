"""Standalone remote helper: stream consistent Plex SQLite backups over stdout.

Executed through ``python3 -c`` on the SSH host; use only the Python standard
library, not MusicSeed imports. Each database is backed up independently.
"""

import sqlite3
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from pathlib import Path

NAMES = ("com.plexapp.plugins.library.db", "com.plexapp.plugins.library.blobs.db")


def stream_snapshot(directory, output):
    """Back up read-only source connections, then stream standalone files."""
    source_dir = Path(directory).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="musicseed-snapshot-") as temp:
        files = []
        for name in NAMES:
            source = source_dir / name
            if name == NAMES[1] and not source.exists():
                continue
            destination = Path(temp) / name
            deadline = time.monotonic() + 300

            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        "SQLite backup exceeded five minutes; retry when Plex is idle"
                    )

            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
                with closing(sqlite3.connect(destination)) as dst:
                    # Backup includes committed WAL pages without copying live sidecars.
                    # Unlike VACUUM, it does not rebuild Plex's custom indexes/collations.
                    src.backup(dst, pages=1024, progress=progress)
                    dst.execute("PRAGMA journal_mode=DELETE")
            files.append(destination)

        with tarfile.open(fileobj=output, mode="w|") as archive:
            for path in files:
                archive.add(path, arcname=path.name, recursive=False)


if __name__ == "__main__":
    stream_snapshot(sys.argv[1], sys.stdout.buffer)
