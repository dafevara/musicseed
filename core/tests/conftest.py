"""Shared fixtures for core tests.

Patches ``discovery.read_plex_token`` to return ``None`` so tests never read
the real Plex installation's ``Preferences.xml`` / ``.LocalAdminToken``.
"""

import pytest
from musicseed.services import discovery


@pytest.fixture(autouse=True)
def no_local_plex_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "read_plex_token", lambda *a, **k: None)
