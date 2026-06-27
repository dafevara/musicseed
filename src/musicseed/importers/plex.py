"""Plex SQLite database importer."""

import sqlite3
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from sqlalchemy.orm import Session

from musicseed.db.models import (
    Album,
    Artist,
    Genre,
    Mood,
    PlayHistory,
    Style,
    Track,
    TrackStats,
)
from musicseed.logging_config import get_logger

console = Console()
logger = get_logger("importers.plex")

# Plex metadata_type values
METADATA_TYPE_ARTIST = 8
METADATA_TYPE_ALBUM = 9
METADATA_TYPE_TRACK = 10

# Plex tag_type values
TAG_TYPE_GENRE = 1
TAG_TYPE_MOOD = 300
TAG_TYPE_STYLE = 301
TAG_TYPE_MBID = 314


@dataclass
class PlexTrackRow:
    """Raw track data from Plex database."""
    id: int
    guid: str
    title: str
    title_sort: str | None
    parent_id: int | None  # album id
    grandparent_id: int | None  # artist id (via album)
    duration: int | None
    index: int | None  # track number
    year: int | None
    added_at: int | None
    updated_at: int | None


@dataclass
class PlexAlbumRow:
    """Raw album data from Plex database."""
    id: int
    guid: str
    title: str
    title_sort: str | None
    parent_id: int | None  # artist id
    year: int | None
    studio: str | None  # label
    added_at: int | None


@dataclass
class PlexArtistRow:
    """Raw artist data from Plex database."""
    id: int
    guid: str
    title: str
    title_sort: str | None
    added_at: int | None


def extract_mbid(tag_value: str) -> str | None:
    """Extract MusicBrainz ID from Plex tag format.

    Format: mbid://xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    """
    if tag_value and tag_value.startswith("mbid://"):
        return tag_value[7:]  # Remove 'mbid://' prefix
    return None


class PlexImporter:
    """Import music metadata from Plex SQLite database."""

    def __init__(self, db_path: Path, library_name: str = "Music"):
        self.db_path = db_path
        self.library_name = library_name
        self._conn: sqlite3.Connection | None = None
        self._library_section_id: int | None = None

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite connection (read-only)."""
        if self._conn is None:
            # Open in read-only mode using URI
            uri = f"file:{self.db_path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True)
            self._conn.row_factory = sqlite3.Row
            # Handle non-UTF-8 text by replacing invalid characters
            self._conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        return self._conn

    def _get_library_section_id(self) -> int:
        """Get the library section ID for the music library."""
        if self._library_section_id is not None:
            return self._library_section_id

        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT id FROM library_sections
            WHERE name = ? AND section_type = 8
            """,
            (self.library_name,)
        )
        row = cursor.fetchone()
        if row is None:
            # Try to find any music library
            cursor = conn.execute(
                "SELECT id, name FROM library_sections WHERE section_type = 8"
            )
            rows = cursor.fetchall()
            if rows:
                available = ", ".join(f"'{r['name']}'" for r in rows)
                raise ValueError(
                    f"Library '{self.library_name}' not found. "
                    f"Available music libraries: {available}"
                )
            raise ValueError("No music libraries found in Plex database")

        self._library_section_id = row["id"]
        return self._library_section_id

    def get_counts(self) -> dict[str, int]:
        """Get counts of artists, albums, and tracks in the library."""
        conn = self._get_connection()
        section_id = self._get_library_section_id()

        counts = {}
        for name, metadata_type in [
            ("artists", METADATA_TYPE_ARTIST),
            ("albums", METADATA_TYPE_ALBUM),
            ("tracks", METADATA_TYPE_TRACK),
        ]:
            cursor = conn.execute(
                """
                SELECT COUNT(*) as count FROM metadata_items
                WHERE library_section_id = ? AND metadata_type = ?
                """,
                (section_id, metadata_type)
            )
            counts[name] = cursor.fetchone()["count"]

        # Play history count
        cursor = conn.execute(
            """
            SELECT COUNT(*) as count FROM metadata_item_views
            WHERE library_section_id = ? AND metadata_type = ?
            """,
            (section_id, METADATA_TYPE_TRACK)
        )
        counts["play_history"] = cursor.fetchone()["count"]

        return counts

    def iter_artists(self) -> Generator[PlexArtistRow, None, None]:
        """Iterate over all artists in the library."""
        conn = self._get_connection()
        section_id = self._get_library_section_id()

        cursor = conn.execute(
            """
            SELECT id, guid, title, title_sort, added_at
            FROM metadata_items
            WHERE library_section_id = ? AND metadata_type = ?
            ORDER BY id
            """,
            (section_id, METADATA_TYPE_ARTIST)
        )

        for row in cursor:
            yield PlexArtistRow(
                id=row["id"],
                guid=row["guid"],
                title=row["title"],
                title_sort=row["title_sort"],
                added_at=row["added_at"],
            )

    def iter_albums(self) -> Generator[PlexAlbumRow, None, None]:
        """Iterate over all albums in the library."""
        conn = self._get_connection()
        section_id = self._get_library_section_id()

        cursor = conn.execute(
            """
            SELECT id, guid, title, title_sort, parent_id, year, studio, added_at
            FROM metadata_items
            WHERE library_section_id = ? AND metadata_type = ?
            ORDER BY id
            """,
            (section_id, METADATA_TYPE_ALBUM)
        )

        for row in cursor:
            yield PlexAlbumRow(
                id=row["id"],
                guid=row["guid"],
                title=row["title"],
                title_sort=row["title_sort"],
                parent_id=row["parent_id"],
                year=row["year"],
                studio=row["studio"],
                added_at=row["added_at"],
            )

    def iter_tracks(self) -> Generator[PlexTrackRow, None, None]:
        """Iterate over all tracks in the library."""
        conn = self._get_connection()
        section_id = self._get_library_section_id()

        logger.debug(f"Querying tracks for library section {section_id}")

        cursor = conn.execute(
            """
            SELECT
                mi.id, mi.guid, mi.title, mi.title_sort,
                mi.parent_id, mi.duration, mi."index", mi.year,
                mi.added_at, mi.updated_at,
                album.parent_id as grandparent_id
            FROM metadata_items mi
            LEFT JOIN metadata_items album ON mi.parent_id = album.id
            WHERE mi.library_section_id = ? AND mi.metadata_type = ?
            ORDER BY mi.id
            """,
            (section_id, METADATA_TYPE_TRACK)
        )

        for row in cursor:
            yield PlexTrackRow(
                id=row["id"],
                guid=row["guid"],
                title=row["title"],
                title_sort=row["title_sort"],
                parent_id=row["parent_id"],
                grandparent_id=row["grandparent_id"],
                duration=row["duration"],
                index=row["index"],
                year=row["year"],
                added_at=row["added_at"],
                updated_at=row["updated_at"],
            )

    def get_track_tags(
        self,
        track_id: int,
        album_id: int | None = None,
        artist_id: int | None = None,
    ) -> dict[str, list[str]]:
        """Get track tags, inheriting styles from album/artist rows.

        Plex stores genre, mood, and MBID taggings directly on tracks in this
        library, but style taggings are attached to album and artist rows.
        Recording MBIDs must not be inherited from album/artist rows because
        those identifiers refer to different MusicBrainz entity types.
        """
        conn = self._get_connection()

        cursor = conn.execute(
            """
            SELECT t.tag, t.tag_type
            FROM tags t
            JOIN taggings tg ON t.id = tg.tag_id
            WHERE tg.metadata_item_id = ?
            AND t.tag_type IN (?, ?, ?, ?)
            """,
            (track_id, TAG_TYPE_GENRE, TAG_TYPE_MOOD, TAG_TYPE_STYLE, TAG_TYPE_MBID),
        )

        tags: dict[str, list[str]] = {
            "genres": [],
            "moods": [],
            "styles": [],
            "mbid": [],
        }

        for row in cursor:
            tag_type = row["tag_type"]
            tag_value = row["tag"]

            if tag_type == TAG_TYPE_GENRE:
                tags["genres"].append(tag_value)
            elif tag_type == TAG_TYPE_MOOD:
                tags["moods"].append(tag_value)
            elif tag_type == TAG_TYPE_STYLE:
                tags["styles"].append(tag_value)
            elif tag_type == TAG_TYPE_MBID:
                mbid = extract_mbid(tag_value)
                if mbid:
                    tags["mbid"].append(mbid)

        inherited_ids = [item_id for item_id in (album_id, artist_id) if item_id is not None]
        if inherited_ids:
            placeholders = ",".join("?" for _ in inherited_ids)
            style_cursor = conn.execute(
                f"""
                SELECT DISTINCT t.tag
                FROM tags t
                JOIN taggings tg ON t.id = tg.tag_id
                WHERE tg.metadata_item_id IN ({placeholders})
                AND t.tag_type = ?
                """,
                (*inherited_ids, TAG_TYPE_STYLE),
            )
            for row in style_cursor:
                if row["tag"] not in tags["styles"]:
                    tags["styles"].append(row["tag"])

        return tags

    def get_track_file_path(self, track_id: int) -> str | None:
        """Get the file path for a track."""
        conn = self._get_connection()

        cursor = conn.execute(
            """
            SELECT mp.file
            FROM media_parts mp
            JOIN media_items mi ON mp.media_item_id = mi.id
            WHERE mi.metadata_item_id = ?
            LIMIT 1
            """,
            (track_id,)
        )

        row = cursor.fetchone()
        return row["file"] if row else None

    def get_play_history(self) -> Generator[dict, None, None]:
        """Get play history for all tracks."""
        conn = self._get_connection()
        section_id = self._get_library_section_id()

        cursor = conn.execute(
            """
            SELECT id, guid, viewed_at, device_id
            FROM metadata_item_views
            WHERE library_section_id = ? AND metadata_type = ?
            ORDER BY viewed_at
            """,
            (section_id, METADATA_TYPE_TRACK)
        )

        for row in cursor:
            yield {
                "plex_view_id": row["id"],
                "plex_guid": row["guid"],
                "viewed_at": row["viewed_at"],
                "device_id": row["device_id"],
            }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


def import_from_plex(
    session: Session,
    plex_db_path: Path,
    library_name: str = "Music",
    full_import: bool = False,
) -> dict[str, int]:
    """Import music library from Plex database.

    Args:
        session: SQLAlchemy session
        plex_db_path: Path to Plex SQLite database
        library_name: Name of the music library in Plex
        full_import: If True, delete existing data first

    Returns:
        Dictionary with import counts
    """
    logger.info(f"Starting Plex import from {plex_db_path}")
    logger.debug(f"Library: {library_name}, full_import: {full_import}")

    importer = PlexImporter(plex_db_path, library_name)

    try:
        logger.debug("Getting library counts...")
        counts = importer.get_counts()
        console.print(
            f"  Found {counts['artists']:,} artists, "
            f"{counts['albums']:,} albums, {counts['tracks']:,} tracks"
        )
        console.print(f"  Found {counts['play_history']:,} play history entries\n")

        # Maps from Plex ID to our ID
        artist_map: dict[int, int] = {}
        album_map: dict[int, int] = {}
        track_map: dict[int, int] = {}  # plex_id -> our track id
        guid_to_track: dict[str, int] = {}  # plex_guid -> our track id

        # Tag caches
        genre_cache: dict[str, Genre] = {}
        mood_cache: dict[str, Mood] = {}
        style_cache: dict[str, Style] = {}

        imported = {"artists": 0, "albums": 0, "tracks": 0, "play_history": 0}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            # Import artists
            artist_task = progress.add_task("Importing artists...", total=counts["artists"])
            for plex_artist in importer.iter_artists():
                # Check if already exists
                existing = session.query(Artist).filter_by(plex_id=plex_artist.id).first()
                if existing and not full_import:
                    artist_map[plex_artist.id] = existing.id
                    progress.advance(artist_task)
                    continue

                artist = existing or Artist()
                artist.name = plex_artist.title
                artist.name_sort = plex_artist.title_sort
                artist.plex_id = plex_artist.id
                artist.plex_guid = plex_artist.guid

                if not existing:
                    session.add(artist)
                    session.flush()  # Get the ID
                    imported["artists"] += 1

                artist_map[plex_artist.id] = artist.id
                progress.advance(artist_task)

            # Import albums
            album_task = progress.add_task("Importing albums...", total=counts["albums"])
            for plex_album in importer.iter_albums():
                existing = session.query(Album).filter_by(plex_id=plex_album.id).first()
                if existing and not full_import:
                    album_map[plex_album.id] = existing.id
                    progress.advance(album_task)
                    continue

                album = existing or Album()
                album.title = plex_album.title
                album.title_sort = plex_album.title_sort
                album.year = plex_album.year
                album.label = plex_album.studio
                album.plex_id = plex_album.id
                album.plex_guid = plex_album.guid

                # Link to artist
                if plex_album.parent_id and plex_album.parent_id in artist_map:
                    album.artist_id = artist_map[plex_album.parent_id]

                if not existing:
                    session.add(album)
                    session.flush()
                    imported["albums"] += 1

                album_map[plex_album.id] = album.id
                progress.advance(album_task)

            # Import tracks
            track_task = progress.add_task("Importing tracks...", total=counts["tracks"])
            for plex_track in importer.iter_tracks():
                existing = session.query(Track).filter_by(plex_id=plex_track.id).first()
                track = existing or Track()
                track.title = plex_track.title
                track.title_sort = plex_track.title_sort
                track.duration_ms = plex_track.duration
                track.track_number = plex_track.index
                track.year = plex_track.year
                track.plex_id = plex_track.id
                track.plex_guid = plex_track.guid

                # Link to album
                if plex_track.parent_id and plex_track.parent_id in album_map:
                    track.album_id = album_map[plex_track.parent_id]

                # Link to artist (via album's parent)
                if plex_track.grandparent_id and plex_track.grandparent_id in artist_map:
                    track.artist_id = artist_map[plex_track.grandparent_id]

                # Get file path
                file_path = importer.get_track_file_path(plex_track.id)
                if file_path:
                    track.file_path = file_path

                # Get tags
                tags = importer.get_track_tags(
                    plex_track.id,
                    album_id=plex_track.parent_id,
                    artist_id=plex_track.grandparent_id,
                )

                # Set MBID if available
                if tags["mbid"]:
                    track.mbid = tags["mbid"][0]
                    track.match_tier = 1  # Plex MBID = high confidence

                if not existing:
                    session.add(track)
                    session.flush()
                    imported["tracks"] += 1

                track_map[plex_track.id] = track.id
                guid_to_track[plex_track.guid] = track.id

                # Add genre associations
                for genre_name in tags["genres"]:
                    if genre_name not in genre_cache:
                        genre = session.query(Genre).filter_by(name=genre_name).first()
                        if not genre:
                            genre = Genre(name=genre_name)
                            session.add(genre)
                            session.flush()
                        genre_cache[genre_name] = genre
                    if genre_cache[genre_name] not in track.genres:
                        track.genres.append(genre_cache[genre_name])

                # Add mood associations
                for mood_name in tags["moods"]:
                    if mood_name not in mood_cache:
                        mood = session.query(Mood).filter_by(name=mood_name).first()
                        if not mood:
                            mood = Mood(name=mood_name)
                            session.add(mood)
                            session.flush()
                        mood_cache[mood_name] = mood
                    if mood_cache[mood_name] not in track.moods:
                        track.moods.append(mood_cache[mood_name])

                # Add style associations
                for style_name in tags["styles"]:
                    if style_name not in style_cache:
                        style = session.query(Style).filter_by(name=style_name).first()
                        if not style:
                            style = Style(name=style_name)
                            session.add(style)
                            session.flush()
                        style_cache[style_name] = style
                    if style_cache[style_name] not in track.styles:
                        track.styles.append(style_cache[style_name])

                progress.advance(track_task)

            # Commit tracks before play history
            session.commit()

            # Import play history
            history_task = progress.add_task(
                "Importing play history...", total=counts["play_history"]
            )
            play_counts: dict[int, int] = {}  # track_id -> count
            last_played: dict[int, datetime] = {}  # track_id -> last played

            for entry in importer.get_play_history():
                plex_guid = entry["plex_guid"]
                if plex_guid not in guid_to_track:
                    progress.advance(history_task)
                    continue

                track_id = guid_to_track[plex_guid]

                # Check if this exact entry already exists
                existing = session.query(PlayHistory).filter_by(
                    plex_view_id=entry["plex_view_id"]
                ).first()

                if not existing:
                    played_at = (
                        datetime.fromtimestamp(entry["viewed_at"])
                        if entry["viewed_at"]
                        else datetime.now()
                    )

                    play_entry = PlayHistory(
                        track_id=track_id,
                        played_at=played_at,
                        device_id=entry["device_id"],
                        plex_view_id=entry["plex_view_id"],
                    )
                    session.add(play_entry)
                    imported["play_history"] += 1

                    # Track stats
                    play_counts[track_id] = play_counts.get(track_id, 0) + 1
                    if track_id not in last_played or played_at > last_played[track_id]:
                        last_played[track_id] = played_at

                progress.advance(history_task)

            # Update track stats
            stats_task = progress.add_task("Updating track stats...", total=len(play_counts))
            for track_id, count in play_counts.items():
                stats = session.query(TrackStats).filter_by(track_id=track_id).first()
                if not stats:
                    stats = TrackStats(track_id=track_id)
                    session.add(stats)

                stats.play_count = count
                stats.last_played_at = last_played.get(track_id)
                progress.advance(stats_task)

            session.commit()

        return imported
    except Exception as e:
        logger.error(f"Error importing from Plex: {e}")
        logger.error(traceback.format_exc())
        raise e

    finally:
        importer.close()
