"""Core services run against an explicitly supplied context (MUS-77)."""

from musicseed.config import Config
from musicseed.context import MusicSeedContext
from musicseed.services.library import get_status, initialize_database
from musicseed.services.typeahead import search_tracks


def _context_for(db_path) -> MusicSeedContext:
    return MusicSeedContext(
        Config.model_validate({"database": {"path": str(db_path)}})
    )


def test_services_accept_an_explicit_context(tmp_path):
    db_path = tmp_path / "musicseed.db"
    ctx = _context_for(db_path)

    initialize_database(context=ctx)

    status = get_status(context=ctx)
    assert status.db_path == str(db_path)
    assert status.track_count == 0

    assert search_tracks("ab", context=ctx) == []


def test_explicit_contexts_are_isolated(tmp_path):
    ctx_a = _context_for(tmp_path / "a" / "musicseed.db")
    ctx_b = _context_for(tmp_path / "b" / "musicseed.db")

    initialize_database(context=ctx_a)
    initialize_database(context=ctx_b)

    assert get_status(context=ctx_a).db_path == str(tmp_path / "a" / "musicseed.db")
    assert get_status(context=ctx_b).db_path == str(tmp_path / "b" / "musicseed.db")
