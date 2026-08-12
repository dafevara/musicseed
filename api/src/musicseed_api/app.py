"""Application assembly for the MusicSeed REST API.

Exposes every MusicSeed operation as a JSON endpoint. The ``handlers/``
layer underneath contains the real orchestration — route modules here just
parse HTTP and delegate.
"""

from __future__ import annotations

from fastapi import FastAPI

from musicseed_api.routes import (
    dashboard,
    discovery,
    enrichment,
    jobs,
    library,
    playlists,
    recommend,
    sonic,
)


def create_app() -> FastAPI:
    app = FastAPI(title="MusicSeed API", version="0.1.0")
    app.include_router(discovery.router)
    app.include_router(library.router)
    app.include_router(enrichment.router)
    app.include_router(recommend.router)
    app.include_router(sonic.router)
    app.include_router(dashboard.router)
    app.include_router(jobs.router)
    app.include_router(playlists.router)
    return app


app = create_app()
