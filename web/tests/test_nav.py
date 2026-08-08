"""Shell navigation tests.

Cover the two things the shell promises: navigation is present on every page,
and the active section is marked from the server-rendered request path.
"""

import re

import pytest
from conftest import make_dashboard, make_discovery
from fastapi.testclient import TestClient
from musicseed_web.app import create_app
from musicseed_web.nav import SECTIONS, active_section
from musicseed_web.routes import dashboard as dashboard_routes
from musicseed_web.routes import home

client = TestClient(create_app())

_NAV_BLOCK = re.compile(r'<nav class="site-nav".*?</nav>', re.S)
_ACTIVE_LINK = re.compile(r'<a[^>]*aria-current="page"[^>]*>(.*?)</a>', re.S)

_AVAILABLE = [s for s in SECTIONS if s.available]
_UNAVAILABLE = [s for s in SECTIONS if not s.available]


@pytest.fixture(autouse=True)
def _offline(monkeypatch) -> None:
    """Keep every page render away from Plex, the filesystem, and the network."""
    monkeypatch.setattr(home, "discover", lambda **kw: make_discovery())
    monkeypatch.setattr(home, "get_dashboard", make_dashboard)
    monkeypatch.setattr(dashboard_routes, "get_dashboard", make_dashboard)


def _nav_of(path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, path
    match = _NAV_BLOCK.search(response.text)
    assert match is not None, f"no navigation rendered on {path}"
    return match.group(0)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "library"),
        ("/dashboard", "library"),
        ("/dashboard/status", "library"),
        ("/setup", "settings"),
        ("/setup/results", "settings"),
        ("/healthz", None),
        ("/fragments/clock", None),
    ],
)
def test_active_section_resolves_from_path(path: str, expected: str | None) -> None:
    assert active_section(path) == expected


@pytest.mark.parametrize(
    ("path", "expected_label"),
    [
        ("/", "Library"),
        ("/dashboard", "Library"),
        ("/setup", "Settings"),
    ],
)
def test_route_marks_exactly_one_active_section(path: str, expected_label: str) -> None:
    nav = _nav_of(path)
    active = _ACTIVE_LINK.findall(nav)
    assert len(active) == 1, f"{path} marked {len(active)} sections active"
    assert expected_label in active[0]
    assert nav.count("is-active") == 1


@pytest.mark.parametrize("path", ["/", "/dashboard", "/setup"])
def test_navigation_lists_every_section(path: str) -> None:
    nav = _nav_of(path)
    for section in SECTIONS:
        assert section.label in nav, f"{section.label} missing from nav on {path}"


@pytest.mark.parametrize("path", ["/", "/dashboard", "/setup"])
def test_sections_without_a_screen_are_not_links(path: str) -> None:
    nav = _nav_of(path)
    # Only the sections that have a screen are anchors; the rest are inert.
    assert nav.count("<a ") == len(_AVAILABLE)
    assert nav.count('aria-disabled="true"') == len(_UNAVAILABLE)
    hrefs = set(re.findall(r'<a[^>]*href="([^"]+)"', nav))
    assert hrefs == {s.href for s in _AVAILABLE}


def test_setup_page_carries_navigation() -> None:
    # The wizard is a section of the shell, not a page outside it.
    assert "Settings" in _nav_of("/setup")
