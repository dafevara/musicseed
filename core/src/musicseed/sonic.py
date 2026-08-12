"""Plex sonic analysis vectors, read directly from Plex at query time.

Plex stores a sonic-analysis vector per analyzed track in
``com.plexapp.plugins.library.blobs.db``. MusicSeed reads those vectors straight
from that database instead of copying them into its own schema — the whole
library is a few megabytes in memory, so there is nothing to gain from storing a
second copy that can drift out of date.

Both Plex databases are opened read-only and are in WAL mode, so loading vectors
neither blocks nor is blocked by a running Plex Media Server.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import numpy as np

from musicseed.config import get_config
from musicseed.exceptions import NotFoundError
from musicseed.logging_config import get_logger

logger = get_logger("sonic")

# Plex blob/metadata discriminators (see importers.plex for the metadata_type map).
PLEX_SONIC_BLOB_TYPE = 7
METADATA_TYPE_TRACK = 10
MUSIC_SECTION_TYPE = 8

# Plex sonic vectors are natively 50-dimensional.
PLEX_SONIC_DIM = 50

_VECTOR_QUERY = """
    SELECT mi.id AS plex_id, b.blob
    FROM blobs b
    JOIN mainlib.metadata_items mi
      ON b.linked_type = 'metadata_item' AND b.linked_id = mi.id
    JOIN mainlib.library_sections ls ON ls.id = mi.library_section_id
    WHERE b.blob_type = ?
      AND b.blob IS NOT NULL
      AND mi.metadata_type = ?
      AND mi.deleted_at IS NULL
      AND ls.name = ?
      AND ls.section_type = ?
    ORDER BY mi.id
"""


def decode_sonic_blob(blob: bytes) -> list[float] | None:
    """Decode one Plex sonic blob (gzipped ASCII CSV) into a float vector.

    Returns None when the blob is unreadable or is not the expected dimension.
    """
    try:
        text = gzip.decompress(blob).decode("ascii")
        values = [float(value) for value in text.split(",") if value]
    except (OSError, UnicodeDecodeError, ValueError):
        return None

    if len(values) != PLEX_SONIC_DIM:
        return None

    return values


class SonicVectors:
    """An in-memory view of a Plex music library's sonic vectors.

    Vectors are stored as one L2-normalized ``(n_tracks, PLEX_SONIC_DIM)`` matrix
    so similarity search is a single matrix multiplication.
    """

    def __init__(self, plex_ids: list[int], matrix: np.ndarray) -> None:
        self._index_by_plex_id = {plex_id: i for i, plex_id in enumerate(plex_ids)}
        self._plex_ids = np.asarray(plex_ids, dtype=np.int64)
        self._matrix = matrix
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self._normalized = matrix / np.where(norms == 0, 1.0, norms)

    def __len__(self) -> int:
        return len(self._index_by_plex_id)

    def __contains__(self, plex_id: object) -> bool:
        return plex_id in self._index_by_plex_id

    @property
    def plex_ids(self) -> set[int]:
        """Every Plex track id that has a sonic vector."""
        return set(self._index_by_plex_id)

    def get(self, plex_id: int | None) -> np.ndarray | None:
        """Return the raw vector for a Plex track id, or None if it has none."""
        if plex_id is None:
            return None
        index = self._index_by_plex_id.get(plex_id)
        if index is None:
            return None
        return self._matrix[index]

    def nearest(self, query: np.ndarray, limit: int) -> list[int]:
        """Return the Plex ids most cosine-similar to ``query``, best first."""
        if limit <= 0 or len(self) == 0:
            return []

        vector = np.asarray(query, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return []

        similarities = self._normalized @ (vector / norm)
        limit = min(limit, similarities.shape[0])
        top = np.argpartition(-similarities, limit - 1)[:limit]
        top = top[np.argsort(-similarities[top])]
        return [int(plex_id) for plex_id in self._plex_ids[top]]


def load_sonic_vectors(
    plex_db_path: Path,
    blobs_db_path: Path,
    library_name: str,
) -> SonicVectors:
    """Read every sonic vector for one Plex music library.

    Raises:
        NotFoundError: if either Plex database file is missing or unreadable.
    """
    if not plex_db_path.exists():
        raise NotFoundError(f"Plex database not found at {plex_db_path}")
    if not blobs_db_path.exists():
        raise NotFoundError(
            f"Plex sonic analysis database not found at {blobs_db_path}. "
            "MusicSeed reads sonic vectors directly from Plex; recommendations "
            "need this file."
        )

    try:
        conn = sqlite3.connect(f"file:{blobs_db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("ATTACH DATABASE ? AS mainlib", (f"file:{plex_db_path}?mode=ro",))
    except sqlite3.Error as e:
        raise NotFoundError(
            f"Could not open the Plex databases ({blobs_db_path}, {plex_db_path}): {e}"
        ) from e

    plex_ids: list[int] = []
    vectors: list[list[float]] = []
    invalid = 0
    try:
        cursor = conn.execute(
            _VECTOR_QUERY,
            (PLEX_SONIC_BLOB_TYPE, METADATA_TYPE_TRACK, library_name, MUSIC_SECTION_TYPE),
        )
        for row in cursor:
            vector = decode_sonic_blob(row["blob"])
            if vector is None:
                invalid += 1
                continue
            plex_ids.append(row["plex_id"])
            vectors.append(vector)
    finally:
        conn.close()

    if invalid:
        logger.warning(f"Skipped {invalid} Plex sonic blobs that could not be decoded")

    matrix = (
        np.asarray(vectors, dtype=np.float32)
        if vectors
        else np.empty((0, PLEX_SONIC_DIM), dtype=np.float32)
    )
    logger.info(f"Loaded {len(plex_ids)} Plex sonic vectors for library '{library_name}'")
    return SonicVectors(plex_ids, matrix)


# Global instance (lazy loaded), mirroring the config module's pattern.
_vectors: SonicVectors | None = None
# Signature of the Plex blobs database files at the time ``_vectors`` was
# loaded, so a change (newly analyzed tracks) invalidates the cache.
_vectors_signature: tuple | None = None


def _blobs_signature(blobs_db_path: Path) -> tuple:
    """A cheap fingerprint of the blobs DB (main + WAL) used to detect change.

    Plex appends sonic blobs to the WAL file before checkpointing, so both
    files are inspected; ``(mtime, size)`` per file is enough to notice a new
    analysis without re-reading the database.
    """
    parts: list[tuple[float, int] | None] = []
    for candidate in (blobs_db_path, Path(f"{blobs_db_path}-wal")):
        try:
            st = candidate.stat()
            parts.append((st.st_mtime, st.st_size))
        except OSError:
            parts.append(None)
    return tuple(parts)


def get_sonic_vectors() -> SonicVectors:
    """Get the global sonic vector store, loading it on first use.

    Cached because recommendation flows (notably playlist population) run many
    seed queries in one process and must not re-read Plex each time. The cache
    reloads whenever the underlying blobs database changes, so newly analyzed
    tracks contribute to scoring without a process restart.
    """
    global _vectors, _vectors_signature
    config = get_config()
    blobs_db_path = config.plex.blobs_db_path_expanded
    signature = _blobs_signature(blobs_db_path)
    if _vectors is not None and signature == _vectors_signature:
        return _vectors
    _vectors = load_sonic_vectors(
        plex_db_path=config.plex.db_path_expanded,
        blobs_db_path=blobs_db_path,
        library_name=config.plex.library,
    )
    _vectors_signature = signature
    return _vectors


def reset_sonic_vectors() -> None:
    """Drop the cached vectors (useful for testing or config changes)."""
    global _vectors, _vectors_signature
    _vectors = None
    _vectors_signature = None
