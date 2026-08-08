"""Task-based navigation for the web shell.

Every page renders the same section list. Which section is active is decided
here from the request path — server-side only, so no client-side router or
application state is involved. Sections whose screen does not exist yet carry
no ``href`` and render as inert labels rather than dead links.
"""

from dataclasses import dataclass

from starlette.requests import Request


@dataclass(frozen=True)
class Section:
    """One entry in the shell navigation."""

    key: str
    label: str
    href: str | None = None
    note: str = ""

    @property
    def available(self) -> bool:
        return self.href is not None


#: Rendered in order on every page. ``Recommend``, ``Playlists``, and
#: ``Activity`` get their screens in MUS-19, MUS-21, and MUS-22; until then
#: they are shown as unavailable so the shell still expresses the full job.
SECTIONS: tuple[Section, ...] = (
    Section("library", "Library", "/"),
    Section("recommend", "Recommend", note="soon"),
    Section("playlists", "Playlists", note="soon"),
    Section("activity", "Activity", note="soon"),
    Section("settings", "Settings", "/setup"),
)

#: Longest-prefix-first, so ``/dashboard/status`` resolves like ``/dashboard``.
_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/setup", "settings"),
    ("/dashboard", "library"),
)


def active_section(path: str) -> str | None:
    """Return the active section key for ``path``, or ``None`` when the path
    belongs to no section (``/healthz`` and standalone fragments)."""
    if path == "/":
        return "library"
    for prefix, key in _PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return key
    return None


def nav_context(request: Request) -> dict[str, object]:
    """Template context processor: puts the section list and the active key
    into every rendered template, so navigation cannot go missing on a page."""
    return {
        "nav_sections": SECTIONS,
        "active_section": active_section(request.url.path),
    }
