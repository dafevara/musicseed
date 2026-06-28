"""Embedding generation pipeline for batch processing tracks."""

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from sqlalchemy.orm import Session

from musicseed.db.models import Track
from musicseed.logging_config import get_logger

logger = get_logger("embeddings.pipeline")
console = Console()


@dataclass
class EmbeddingStats:
    """Statistics from embedding generation."""
    total: int
    generated: int
    skipped: int
    errors: int


def get_tracks_to_embed(
    session: Session,
    limit: int | None = None,
    missing_only: bool = False,
) -> list[dict]:
    """Get tracks that need embeddings.

    Args:
        session: Database session
        limit: Max tracks to return
        missing_only: Only get tracks without embeddings

    Returns:
        List of track dicts with id, title, file_path
    """
    query = session.query(
        Track.id,
        Track.title,
        Track.file_path,
    ).filter(Track.file_path.isnot(None))

    if missing_only:
        query = query.filter(
            (Track.embedding_generated.is_(False)) | (Track.embedding_generated.is_(None))
        )

    if limit:
        query = query.limit(limit)

    tracks = []
    for row in query:
        if row.file_path:  # Double check file_path exists
            tracks.append({
                "id": row.id,
                "title": row.title,
                "file_path": row.file_path,
            })

    return tracks


def _process_single_track(args: tuple) -> tuple[int, Any, str | None]:
    """Process a single track (worker function for multiprocessing).

    Args:
        args: Tuple of (track_id, file_path, model_name)

    Returns:
        Tuple of (track_id, embedding_array_or_None, error_message_or_None)
    """
    track_id, file_path, model_name = args

    try:
        # Import here to avoid issues with multiprocessing
        from musicseed.embeddings.essentia_embed import get_embedder

        embedder = get_embedder(model_name)
        embedding = embedder.embed_file(file_path)

        if embedding is not None:
            return (track_id, embedding.tolist(), None)
        else:
            return (track_id, None, "Failed to generate embedding")

    except Exception as e:
        return (track_id, None, str(e))


def run_embedding_pipeline(
    session: Session,
    model: str = "essentia",
    batch_size: int = 10,
    limit: int | None = None,
    missing_only: bool = False,
    workers: int = 4,
) -> EmbeddingStats:
    """Run the embedding generation pipeline.

    Args:
        session: Database session
        model: Embedding model ("essentia" or "simple")
        batch_size: Tracks per batch (for progress updates)
        limit: Max tracks to process
        missing_only: Only process tracks without embeddings
        workers: Number of parallel workers

    Returns:
        Embedding statistics
    """
    logger.info(f"Starting embedding pipeline with {workers} workers")
    logger.info(f"Model: {model}, missing_only: {missing_only}")

    if model == "essentia":
        from musicseed.embeddings.essentia_embed import validate_musicnn_model

        model_path = validate_musicnn_model()
        console.print(f"  Essentia model: {model_path}")

    # Get tracks to process
    tracks = get_tracks_to_embed(session, limit=limit, missing_only=missing_only)

    if not tracks:
        console.print("[yellow]No tracks to process[/yellow]")
        return EmbeddingStats(total=0, generated=0, skipped=0, errors=0)

    console.print(f"  Tracks to process: {len(tracks):,}")
    console.print(f"  Workers: {workers}")
    console.print(f"  Model: {model}\n")

    generated = 0
    skipped = 0
    errors = 0

    # Prepare work items
    work_items = [
        (t["id"], t["file_path"], model)
        for t in tracks
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Generating embeddings ({model})...",
            total=len(tracks),
        )

        # Use ProcessPoolExecutor for CPU-bound work
        # Limit workers to avoid overwhelming the system
        actual_workers = min(workers, mp.cpu_count(), len(tracks))

        with ProcessPoolExecutor(max_workers=actual_workers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(_process_single_track, item): item[0]
                for item in work_items
            }

            # Process results as they complete
            batch_updates = []

            for future in as_completed(futures):
                track_id = futures[future]

                try:
                    result_id, embedding, error = future.result()

                    if embedding is not None:
                        batch_updates.append((result_id, embedding))
                        generated += 1
                    elif error:
                        logger.debug(f"Track {result_id}: {error}")
                        errors += 1
                    else:
                        skipped += 1

                except Exception as e:
                    logger.error(f"Worker error for track {track_id}: {e}")
                    errors += 1

                progress.advance(task)

                # Batch update database periodically
                if len(batch_updates) >= batch_size:
                    _update_embeddings(session, batch_updates, model)
                    batch_updates = []

            # Update remaining
            if batch_updates:
                _update_embeddings(session, batch_updates, model)

    logger.info(f"Embedding complete: {generated} generated, {skipped} skipped, {errors} errors")

    return EmbeddingStats(
        total=len(tracks),
        generated=generated,
        skipped=skipped,
        errors=errors,
    )


def _update_embeddings(
    session: Session,
    updates: list[tuple[int, list[float]]],
    model: str,
) -> None:
    """Batch update embeddings in database.

    Args:
        session: Database session
        updates: List of (track_id, embedding) tuples
        model: Model name used for embedding
    """
    for track_id, embedding in updates:
        track = session.get(Track, track_id)
        if track:
            track.embedding = embedding
            track.embedding_model = model
            track.embedding_generated = True

    session.commit()
    logger.debug(f"Updated {len(updates)} embeddings in database")
