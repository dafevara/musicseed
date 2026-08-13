"""Shared fixtures for core tests.

Patches local Plex discovery so tests never read the real installation.
"""

from pathlib import Path

import pytest
from musicseed.services import discovery


@pytest.fixture(autouse=True)
def isolate_local_plex(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    missing = tmp_path_factory.mktemp("no-plex") / "Plex Media Server"
    monkeypatch.setattr(discovery, "read_plex_token", lambda *a, **k: None)
    monkeypatch.setattr(discovery, "plex_data_dir_candidates", lambda: [missing])
    monkeypatch.setattr(
        discovery,
        "plex_library_db_candidates",
        lambda: [missing / "Plug-in Support" / "Databases" / "com.plexapp.plugins.library.db"],
    )
    monkeypatch.setattr(discovery, "default_plex_data_dir", lambda: missing)
    return missing
