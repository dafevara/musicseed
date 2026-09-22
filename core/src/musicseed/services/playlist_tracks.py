"""Write an approved ordered track selection, without recomputing recommendations."""

from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from musicseed.clients.plex import Playlist, PlexAPIError, PlexClient
from musicseed.context import MusicSeedContext, get_context
from musicseed.db.models import Track
from musicseed.exceptions import ConfigurationError, NotFoundError
from musicseed.services.schemas import ServiceTrack, to_service_track


class PlaylistTracksResult(BaseModel):
    """The created playlist and exact selected tracks, with no invented scores."""

    playlist: Playlist
    tracks: list[ServiceTrack]


def resolve_track_selection(session: Session, track_ids: list[int]) -> list[ServiceTrack]:
    """Resolve every selected local ID in order; reject stale/unmapped selections.

    Duplicates are removed in first-occurrence order. Missing tracks fail the
    entire selection before any Plex write rather than silently writing a subset.
    """
    ids = list(dict.fromkeys(track_ids))
    if not ids:
        return []
    rows = session.query(Track).options(
        selectinload(Track.artist), selectinload(Track.album),
    ).filter(Track.id.in_(ids)).all()
    by_id = {row.id: row for row in rows}
    missing = [track_id for track_id in ids
               if track_id not in by_id or by_id[track_id].plex_id is None]
    if missing:
        raise NotFoundError(
            f"Selected tracks are no longer available in Plex: {missing[:10]}. "
            "Refresh the preview before applying it."
        )
    return [to_service_track(by_id[track_id]) for track_id in ids]


def create_playlist_from_tracks(
    name: str, track_ids: list[int], *, context: MusicSeedContext | None = None,
) -> PlaylistTracksResult:
    """Create a Plex playlist from exactly the approved local IDs, in order.

    No recommendations are generated, and no score/filter policy is reapplied.
    Callers should include approved seed IDs in the selection when desired.
    """
    ctx = context or get_context()
    name = name.strip()
    if not name or not track_ids:
        raise ConfigurationError("A playlist name and approved tracks are required.")
    if not ctx.config.plex.token:
        raise ConfigurationError("plex.token is not configured. Add it to your config file.")
    with ctx.session() as session:
        tracks = resolve_track_selection(session, track_ids)
    client = PlexClient(base_url=ctx.config.plex.url, token=ctx.config.plex.token)
    target_plex_ids = [t.plex_id for t in tracks]
    existing = client.find_playlist(name)
    if existing is not None:
        current_ids = [
            int(i.rating_key) for i in client.get_playlist_tracks(existing.rating_key)
        ]
        if current_ids == target_plex_ids:
            # Retry after a lost response: the playlist already exists with
            # exactly this selection, so report it as created.
            return PlaylistTracksResult(playlist=existing, tracks=tracks)
        raise PlexAPIError(
            f"A playlist named '{name}' already exists in Plex with different "
            f"tracks (id={existing.rating_key}). Choose a different name."
        )
    playlist = client.create_playlist(name, target_plex_ids)
    return PlaylistTracksResult(playlist=playlist, tracks=tracks)
