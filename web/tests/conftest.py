"""Shared fixtures: canned DiscoveryResult objects so route tests never touch
the real Plex installation, filesystem state, or network."""

from musicseed.services.discovery import (
    DatabasePathDiscovery,
    DiscoveryResult,
    FileDiscovery,
    PathCandidate,
    PlexServerDiscovery,
    Reason,
)


def make_discovery(
    *,
    db_exists: bool = True,
    db_reason: Reason = Reason.OK,
    library_db_ok: bool = True,
    library_db_reason: Reason | None = None,
    server_reason: Reason = Reason.OK,
    token_configured: bool = True,
    library_found: bool = True,
) -> DiscoveryResult:
    db_ok = db_reason is Reason.OK
    db = DatabasePathDiscovery(
        path="/tmp/fake/musicseed.db",
        source="default",
        exists=db_exists,
        writable=db_ok,
        creatable=db_reason in (Reason.OK, Reason.PARENT_MISSING),
        reason=db_reason,
        detail=None if db_ok else "Database problem detail.",
        ok=db_ok,
    )

    def file_discovery(ok: bool, reason: Reason | None, path: str) -> FileDiscovery:
        candidate = PathCandidate(
            path=path,
            source="default",
            exists=ok,
            usable=ok,
            reason=Reason.OK if ok else (reason or Reason.NOT_FOUND),
            detail=None if ok else "File problem detail.",
        )
        return FileDiscovery(
            candidates=[candidate], selected=candidate if ok else None, ok=ok
        )

    server_ok = server_reason is Reason.OK
    server = PlexServerDiscovery(
        url="http://localhost:32400",
        source="default",
        token_configured=token_configured,
        server_version="1.41.0" if server_ok else None,
        library="Music",
        library_found=library_found,
        reason=server_reason,
        detail=None if server_ok else "Server problem detail.",
        ok=server_ok,
    )

    library_db = file_discovery(library_db_ok, library_db_reason, "/plex/library.db")
    blobs_db = file_discovery(library_db_ok, library_db_reason, "/plex/library.blobs.db")
    ready = all([db_ok, library_db.ok, blobs_db.ok, server.ok])
    return DiscoveryResult(
        musicseed_db=db,
        plex_library_db=library_db,
        plex_blobs_db=blobs_db,
        plex_server=server,
        ready=ready,
    )
