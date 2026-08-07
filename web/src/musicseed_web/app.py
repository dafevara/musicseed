"""Application assembly for the MusicSeed local web UI.

Thin surface only: routes render templates and call ``musicseed.services``
for real work. No business, Plex, database, or recommendation logic lives
here.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from musicseed.services.jobs import get_manager

from musicseed_web.render import BASE_DIR
from musicseed_web.routes import dashboard, home, jobs, setup


def create_app() -> FastAPI:
    app = FastAPI(title="MusicSeed", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(home.router)
    app.include_router(setup.router)
    app.include_router(dashboard.router)
    app.include_router(jobs.router)

    @app.on_event("shutdown")
    def _cleanup_jobs() -> None:
        get_manager().shutdown()

    return app


app = create_app()
