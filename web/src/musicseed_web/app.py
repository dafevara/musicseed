"""Application assembly for the MusicSeed local web UI.

Thin surface only: routes render templates and call ``musicseed_api.handlers``
for orchestration. The API's JSON routes are mounted at ``/api/`` so every
operation is available to external callers through the same server.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from musicseed.services.jobs import get_manager

from musicseed_api.app import create_app as create_api_app

from musicseed_web.render import BASE_DIR
from musicseed_web.routes import dashboard, home, jobs, recommend, setup


def create_app() -> FastAPI:
    app = FastAPI(title="MusicSeed", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    # Mount the full REST API at /api/
    api_app = create_api_app()
    app.mount("/api", api_app)

    app.include_router(home.router)
    app.include_router(setup.router)
    app.include_router(recommend.router)
    app.include_router(dashboard.router)
    app.include_router(jobs.router)

    @app.on_event("shutdown")
    def _cleanup_jobs() -> None:
        get_manager().shutdown()

    return app


app = create_app()
