"""Programmatic server entry point for the MusicSeed API.

Surfaces start the API through ``serve()`` instead of assembling uvicorn
themselves. Used by the ``musicseed-api`` script entry point. When a static
UI is present, ``create_ui_app()`` mounts the JSON API at ``/api`` and serves
the exported Next.js files from ``/``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from musicseed.logging_config import resolve_log_level, setup_logging
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from musicseed_api.app import app, create_app

_log = logging.getLogger("musicseed")


def _attach_uvicorn_to(logger: logging.Logger) -> None:
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = False
        uv.setLevel(logger.level)
        for handler in logger.handlers:
            uv.addHandler(handler)


def resolve_static_dir() -> Path | None:
    """Return the exported web UI directory, or None if it is not built.

    Resolution order: ``MUSICSEED_STATIC_DIR``, then ``web/out`` walking up
    from this file (git-clone layout).
    """
    env = os.environ.get("MUSICSEED_STATIC_DIR")
    if env:
        candidate = Path(env).expanduser()
        if (candidate / "index.html").is_file():
            return candidate
        return None
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "web" / "out"
        if (candidate / "index.html").is_file():
            return candidate
    return None


class _SPAStaticFiles(StaticFiles):
    """Serve the Next export, falling back to ``index.html`` for client routes."""

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return FileResponse(Path(self.directory) / "index.html")
            raise


def create_ui_app(static_dir: Path | None = None) -> FastAPI:
    """API at ``/api`` plus optional static UI at ``/``.

    ``create_app()`` stays unprefixed for tests and direct JSON clients.
    Missing static files degrade to API-only (still mounted at ``/api``).
    """
    parent = FastAPI(title="MusicSeed", version="0.1.0")
    parent.mount("/api", create_app())
    if static_dir is not None:
        resolved = static_dir if (static_dir / "index.html").is_file() else None
    else:
        resolved = resolve_static_dir()
    if resolved is None:
        _log.warning(
            "No static UI found (set MUSICSEED_STATIC_DIR or run "
            "`npm ci && npm run build` in web/). Serving API only at /api."
        )
        return parent
    parent.mount(
        "/",
        _SPAStaticFiles(directory=resolved, html=True),
        name="ui",
    )
    return parent


def serve(
    host: str,
    port: int,
    on_started: Callable[[], None] | None = None,
    *,
    serve_ui: bool = True,
) -> None:
    """Run the API with uvicorn on ``host``/``port``.

    ``on_started`` is invoked once the server is ready. Blocks until
    shutdown. When ``serve_ui`` is true, serve the static UI if present.
    """
    level = resolve_log_level()
    logger = setup_logging(level=level, console=True, console_level=level)
    _attach_uvicorn_to(logger)
    application = create_ui_app() if serve_ui else app
    uv_level = logging.getLevelName(level).lower()
    config = uvicorn.Config(application, host=host, port=port, log_level=uv_level)
    server = uvicorn.Server(config)
    if on_started is not None:
        watcher = threading.Thread(
            target=_run_when_started, args=(server, on_started), daemon=True
        )
        watcher.start()
    server.run()


def _run_when_started(server: uvicorn.Server, callback: Callable[[], None]) -> None:
    while not server.started:
        if server.should_exit:
            return
        time.sleep(0.05)
    callback()


def main() -> None:
    """Script entry point: ``musicseed``."""
    import argparse
    import webbrowser

    parser = argparse.ArgumentParser(prog="musicseed", description="MusicSeed API and web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--open", action="store_true", help="Open the UI in a browser")
    parser.add_argument("--no-ui", action="store_true", help="Serve JSON only (no static UI)")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    on_started = (lambda: webbrowser.open(url)) if args.open else None
    serve(host=args.host, port=args.port, on_started=on_started, serve_ui=not args.no_ui)
