"""Playlist recommendation orchestration."""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from musicseed.db.models import Artist, Track
from musicseed.recommender.candidates import build_candidate_pool
from musicseed.recommender.scoring import (
    ScoreBreakdown,
    Weights,
    build_seed_profile,
    calculate_score,
)


class Recommendation(BaseModel):
    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    track: Track
    score: ScoreBreakdown
    sources: list[str]


def _track_load_options():
    return (
        selectinload(Track.artist),
        selectinload(Track.album),
        selectinload(Track.moods),
        selectinload(Track.styles),
        selectinload(Track.genres),
        selectinload(Track.stats),
    )


def _format_track(track: Track) -> str:
    artist = track.artist.name if track.artist else "Unknown Artist"
    return f"{artist} - {track.title} (id={track.id})"


def _resolve_seed_text(session: Session, seed_text: str) -> Track:
    text = seed_text.strip()
    query = session.query(Track).options(*_track_load_options())

    if " - " in text:
        artist_text, title_text = [part.strip() for part in text.split(" - ", 1)]
        exact = (
            query.join(Artist, Track.artist_id == Artist.id)
            .filter(func.lower(Artist.name) == artist_text.lower())
            .filter(func.lower(Track.title) == title_text.lower())
            .first()
        )
        if exact:
            return exact

        matches = (
            query.join(Artist, Track.artist_id == Artist.id)
            .filter(Artist.name.ilike(f"%{artist_text}%"))
            .filter(Track.title.ilike(f"%{title_text}%"))
            .limit(6)
            .all()
        )
    else:
        exact = query.filter(func.lower(Track.title) == text.lower()).first()
        if exact:
            return exact
        matches = query.filter(Track.title.ilike(f"%{text}%")).limit(6).all()

    if not matches:
        raise ValueError(f"No seed track matched: {seed_text}")
    if len(matches) > 1:
        options = "; ".join(_format_track(track) for track in matches[:5])
        raise ValueError(f"Seed is ambiguous: {seed_text}. Matches: {options}")
    return matches[0]


def resolve_seed_tracks(
    session: Session,
    *,
    seed_texts: Sequence[str] | None = None,
    seed_ids: Sequence[int] | None = None,
) -> list[Track]:
    """Resolve seed IDs and seed text queries into loaded Track objects."""

    seeds: list[Track] = []
    seen: set[int] = set()

    for track_id in seed_ids or []:
        track = (
            session.query(Track)
            .options(*_track_load_options())
            .filter(Track.id == track_id)
            .one_or_none()
        )
        if track is None:
            raise ValueError(f"No seed track found with id={track_id}")
        if track.id not in seen:
            seeds.append(track)
            seen.add(track.id)

    for seed_text in seed_texts or []:
        track = _resolve_seed_text(session, seed_text)
        if track.id not in seen:
            seeds.append(track)
            seen.add(track.id)

    if not seeds:
        raise ValueError("At least one seed track is required")

    return seeds


def recommend_tracks(
    session: Session,
    *,
    seed_texts: Sequence[str] | None = None,
    seed_ids: Sequence[int] | None = None,
    limit: int = 50,
    weights: Weights | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_tracks_per_artist: int = 3,
    min_score: float | None = None,
) -> tuple[list[Track], list[Recommendation]]:
    """Generate recommendations using multi-source candidates and constrained selection."""

    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    if max_tracks_per_artist <= 0:
        raise ValueError("max_tracks_per_artist must be greater than zero")

    weights = weights or Weights()
    seed_tracks = resolve_seed_tracks(session, seed_texts=seed_texts, seed_ids=seed_ids)
    seed_profile = build_seed_profile(seed_tracks)
    candidate_pool = build_candidate_pool(
        session,
        seed_profile,
        limit=limit,
        year_min=year_min,
        year_max=year_max,
    )

    if not candidate_pool.track_ids:
        return seed_tracks, []

    candidates = (
        session.query(Track)
        .options(*_track_load_options())
        .filter(Track.id.in_(candidate_pool.track_ids))
        .all()
    )

    scored = [
        Recommendation(
            track=track,
            score=calculate_score(track, seed_profile, weights),
            sources=candidate_pool.sources_for(track.id),
        )
        for track in candidates
        if track.id not in seed_profile.track_ids
    ]
    scored.sort(key=lambda recommendation: recommendation.score.total, reverse=True)

    selected: list[Recommendation] = []
    artist_counts: dict[int | None, int] = defaultdict(int)

    for recommendation in scored:
        if min_score is not None and recommendation.score.total < min_score:
            break  # sorted descending — everything after this is also below threshold
        artist_id = recommendation.track.artist_id
        if artist_counts[artist_id] >= max_tracks_per_artist:
            continue
        selected.append(recommendation)
        artist_counts[artist_id] += 1
        if len(selected) >= limit:
            break

    return seed_tracks, selected
