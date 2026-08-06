"""Programmatic server entry point for the MusicSeed web app.

Surfaces (currently the ``musicseed web`` CLI command) start the app through
``serve`` instead of assembling uvicorn themselves.
"""

import threading
import time
from collections.abc import Callable

import uvicorn

from musicseed_web.app import app


def serve(host: str, port: int, on_started: Callable[[], None] | None = None) -> None:
    """Run the web app with uvicorn on ``host``/``port``.

    ``on_started`` is invoked once the server is ready to receive requests
    (used by the CLI to open the browser at the right moment). Blocks until
    the server shuts down (e.g. via Ctrl+C, which uvicorn handles gracefully).
    """
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
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
