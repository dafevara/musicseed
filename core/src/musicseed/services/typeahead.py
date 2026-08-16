"""Track typeahead search service — the reusable lookup behind autocomplete."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.orm import joinedload

from musicseed.db.models import Artist, Track
from musicseed.db.session import get_session


class TypeaheadTrack(BaseModel):
    """A minimal, JSON-safe view of a track for autocomplete results."""

    model_config = {"frozen": True}

    id: int
    title: str
    artist: str | None
    album: str | None
    year: int | None


def search_tracks(
    query: str,
    exclude_ids: list[int] | None = None,
    limit: int = 10,
) -> list[TypeaheadTrack]:
    """Search tracks by title or artist name for autocomplete.

    Returns an empty list when the query is shorter than 2 characters. Results
    exclude ``exclude_ids``, are ordered by title, and capped at ``limit``.

    Args:
        query: substring matched (case-insensitively) against track titles
            and artist names.
        exclude_ids: local track ids to leave out of the results.
        limit: maximum number of matches to return.

    Returns:
        Matching tracks as minimal JSON-safe views, ordered by title.
    """
    q = query.strip()
    if len(q) < 2:
        return []

    exclude = exclude_ids or []
    with get_session() as session:
        rows = (
            session.query(Track)
            .options(joinedload(Track.artist), joinedload(Track.album))
            .outerjoin(Artist, Track.artist_id == Artist.id)
            .filter(Track.title.ilike(f"%{q}%") | Artist.name.ilike(f"%{q}%"))
            .filter(~Track.id.in_(exclude) if exclude else True)
            .order_by(Track.title)
            .limit(limit)
            .all()
        )

    return [
        TypeaheadTrack(
            id=track.id,
            title=track.title,
            artist=track.artist.name if track.artist else None,
            album=track.album.title if track.album else None,
            year=track.year,
        )
        for track in rows
    ]
