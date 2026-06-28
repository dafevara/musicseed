"""SQLAlchemy database models."""

from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    name_sort: Mapped[Optional[str]] = mapped_column(String(500))

    # External IDs
    mbid: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    spotify_id: Mapped[Optional[str]] = mapped_column(String(50))

    # Popularity
    spotify_popularity: Mapped[Optional[int]] = mapped_column(SmallInteger)
    spotify_followers: Mapped[Optional[int]] = mapped_column(Integer)

    # Plex reference
    plex_guid: Mapped[Optional[str]] = mapped_column(String(255))
    plex_id: Mapped[Optional[int]] = mapped_column(Integer)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    albums: Mapped[list["Album"]] = relationship("Album", back_populates="artist")
    tracks: Mapped[list["Track"]] = relationship("Track", back_populates="artist")


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    title_sort: Mapped[Optional[str]] = mapped_column(String(500))
    artist_id: Mapped[Optional[int]] = mapped_column(ForeignKey("artists.id"))

    # Metadata
    year: Mapped[Optional[int]] = mapped_column(SmallInteger)
    label: Mapped[Optional[str]] = mapped_column(String(255))

    # External IDs
    mbid: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    spotify_id: Mapped[Optional[str]] = mapped_column(String(50))
    discogs_id: Mapped[Optional[int]] = mapped_column(Integer)

    # Plex reference
    plex_guid: Mapped[Optional[str]] = mapped_column(String(255))
    plex_id: Mapped[Optional[int]] = mapped_column(Integer)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    artist: Mapped[Optional["Artist"]] = relationship("Artist", back_populates="albums")
    tracks: Mapped[list["Track"]] = relationship("Track", back_populates="album")


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    title_sort: Mapped[Optional[str]] = mapped_column(String(500))
    album_id: Mapped[Optional[int]] = mapped_column(ForeignKey("albums.id"))
    artist_id: Mapped[Optional[int]] = mapped_column(ForeignKey("artists.id"))

    # Metadata
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    track_number: Mapped[Optional[int]] = mapped_column(SmallInteger)
    disc_number: Mapped[Optional[int]] = mapped_column(SmallInteger)
    year: Mapped[Optional[int]] = mapped_column(SmallInteger)

    # File info
    file_path: Mapped[Optional[str]] = mapped_column(Text)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64))

    # External IDs
    mbid: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    spotify_id: Mapped[Optional[str]] = mapped_column(String(50))

    # Popularity/enrichment signals
    spotify_popularity: Mapped[Optional[int]] = mapped_column(SmallInteger)
    popularity_score: Mapped[Optional[float]] = mapped_column(Float)  # normalized 0-1
    popularity_source: Mapped[Optional[str]] = mapped_column(String(50))
    listenbrainz_listen_count: Mapped[Optional[int]] = mapped_column(BigInteger)
    listenbrainz_listener_count: Mapped[Optional[int]] = mapped_column(Integer)
    listenbrainz_matched: Mapped[bool] = mapped_column(Boolean, default=False)

    # Embedding (pgvector)
    embedding = mapped_column(Vector(200), nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(50))

    # Plex reference
    plex_guid: Mapped[Optional[str]] = mapped_column(String(255))
    plex_id: Mapped[Optional[int]] = mapped_column(Integer)

    # Enrichment status
    spotify_matched: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    match_tier: Mapped[Optional[int]] = mapped_column(SmallInteger)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    album: Mapped[Optional["Album"]] = relationship("Album", back_populates="tracks")
    artist: Mapped[Optional["Artist"]] = relationship("Artist", back_populates="tracks")
    moods: Mapped[list["Mood"]] = relationship(
        "Mood", secondary="track_moods", back_populates="tracks"
    )
    styles: Mapped[list["Style"]] = relationship(
        "Style", secondary="track_styles", back_populates="tracks"
    )
    genres: Mapped[list["Genre"]] = relationship(
        "Genre", secondary="track_genres", back_populates="tracks"
    )
    stats: Mapped[Optional["TrackStats"]] = relationship(
        "TrackStats", back_populates="track", uselist=False
    )
    play_history: Mapped[list["PlayHistory"]] = relationship(
        "PlayHistory", back_populates="track"
    )


# Tag tables
class Mood(Base):
    __tablename__ = "moods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    tracks: Mapped[list["Track"]] = relationship(
        "Track", secondary="track_moods", back_populates="moods"
    )


class Style(Base):
    __tablename__ = "styles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    tracks: Mapped[list["Track"]] = relationship(
        "Track", secondary="track_styles", back_populates="styles"
    )


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    tracks: Mapped[list["Track"]] = relationship(
        "Track", secondary="track_genres", back_populates="genres"
    )


# Junction tables
class TrackMood(Base):
    __tablename__ = "track_moods"

    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    mood_id: Mapped[int] = mapped_column(
        ForeignKey("moods.id", ondelete="CASCADE"), primary_key=True
    )


class TrackStyle(Base):
    __tablename__ = "track_styles"

    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    style_id: Mapped[int] = mapped_column(
        ForeignKey("styles.id", ondelete="CASCADE"), primary_key=True
    )


class TrackGenre(Base):
    __tablename__ = "track_genres"

    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[int] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True
    )


# Play history
class PlayHistory(Base):
    __tablename__ = "play_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    played_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    device_id: Mapped[Optional[int]] = mapped_column(Integer)
    plex_view_id: Mapped[Optional[int]] = mapped_column(Integer)

    track: Mapped["Track"] = relationship("Track", back_populates="play_history")


class TrackStats(Base):
    __tablename__ = "track_stats"

    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    skip_count: Mapped[int] = mapped_column(Integer, default=0)

    track: Mapped["Track"] = relationship("Track", back_populates="stats")


# Playlists
class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Generation parameters
    seed_track_ids: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer))
    weights: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Plex reference
    plex_playlist_id: Mapped[Optional[int]] = mapped_column(Integer)
    plex_guid: Mapped[Optional[str]] = mapped_column(String(255))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    tracks: Mapped[list["PlaylistTrack"]] = relationship(
        "PlaylistTrack", back_populates="playlist"
    )


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    playlist_id: Mapped[int] = mapped_column(
        ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True
    )
    track_id: Mapped[int] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Float)

    playlist: Mapped["Playlist"] = relationship("Playlist", back_populates="tracks")
    track: Mapped["Track"] = relationship("Track")
