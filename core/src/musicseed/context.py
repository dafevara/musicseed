"""Runtime context that bundles config with its derived database and sonic resources.

MusicSeed's services used to read three pieces of process-global state
directly: the resolved ``Config``, a database engine/session factory, and a
cached ``SonicVectors`` matrix. Those three are all derived from config, so
hiding them behind module singletons made service behavior depend on call
order and forced config changes to reach into ``reset_engine()``.

``MusicSeedContext`` groups them into one object that a surface (or a test)
can construct explicitly and hand to a service. The module-level default
context keeps the existing convenience entry points working without passing a
context everywhere.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from musicseed.config import Config, get_config
from musicseed.db.session import create_engine_for_url, create_session_factory
from musicseed.sonic import SonicVectors, blobs_signature, load_sonic_vectors


@dataclass
class MusicSeedContext:
    """A resolved config plus the lazily-created database and sonic resources.

    The session factory and sonic vectors are built on first use and cached on
    the instance, so a context is cheap to create and safe to reuse across
    many service calls. It is intentionally not frozen: the lazily-populated
    fields are implementation details, not part of its identity.
    """

    config: Config

    _engine: Engine | None = field(default=None, init=False, repr=False)
    _session_factory: sessionmaker | None = field(default=None, init=False, repr=False)
    _sonic_vectors: SonicVectors | None = field(default=None, init=False, repr=False)
    _sonic_signature: tuple | None = field(default=None, init=False, repr=False)

    @property
    def engine(self) -> Engine:
        """The SQLite engine for this context's database (created on first use)."""
        if self._engine is None:
            self._engine = create_engine_for_url(self.config.database.url)
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """A ``sessionmaker`` bound to this context's engine."""
        if self._session_factory is None:
            self._session_factory = create_session_factory(self.engine)
        return self._session_factory

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Open a database session with commit/rollback/close semantics.

        Mirrors ``musicseed.db.session.get_session`` but is bound to this
        context's engine rather than the process-global default.
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @property
    def sonic_vectors(self) -> SonicVectors:
        """Plex sonic vectors for this context's library, cached and reloadable.

        The cache reloads whenever the Plex blobs database changes (newly
        analyzed tracks), matching the historical ``get_sonic_vectors()``
        behavior. Raises ``NotFoundError`` when the Plex databases are
        unavailable.
        """
        blobs_db_path = self.config.plex.blobs_db_path_expanded
        signature = blobs_signature(blobs_db_path)
        if self._sonic_vectors is not None and signature == self._sonic_signature:
            return self._sonic_vectors
        self._sonic_vectors = load_sonic_vectors(
            plex_db_path=self.config.plex.db_path_expanded,
            blobs_db_path=blobs_db_path,
            library_name=self.config.plex.library,
        )
        self._sonic_signature = signature
        return self._sonic_vectors

    def reset_sonic_vectors(self) -> None:
        """Drop this context's cached vectors so the next access reloads them."""
        self._sonic_vectors = None
        self._sonic_signature = None


# The default context used by the legacy module-level convenience functions
# (config.get_config, db.session.get_session, sonic.get_sonic_vectors).
_default_context: MusicSeedContext | None = None


def get_context() -> MusicSeedContext:
    """Return the default context, building it from the global config on first use."""
    global _default_context
    if _default_context is None:
        _default_context = MusicSeedContext(get_config())
    return _default_context


def set_context(context: MusicSeedContext) -> None:
    """Install ``context`` as the default context for the process."""
    global _default_context
    _default_context = context


def reset_context() -> None:
    """Drop the default context so the next access rebuilds it from current config."""
    global _default_context
    _default_context = None
