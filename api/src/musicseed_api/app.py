"""Application assembly for the MusicSeed REST API.

Exposes every MusicSeed operation as a JSON endpoint. The ``handlers/``
layer underneath contains the real orchestration — route modules here just
parse HTTP and delegate.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from musicseed.clients.plex import PlexAPIError
from musicseed.exceptions import (
    ConfigurationError,
    JobConflictError,
    MusicSeedError,
    NotFoundError,
)

from musicseed_api.routes import (
    dashboard,
    discovery,
    enrichment,
    jobs,
    library,
    playlists,
    plex_auth,
    recommend,
    sonic,
)
from musicseed_api.security import (
    CSRF_ENDPOINT,
    get_csrf_secret,
    issue_csrf_token,
    security_filter,
)


def create_app() -> FastAPI:
    """Assemble the JSON API: mount every route module and register the error contract.

    Every route parses HTTP, calls a framework-free handler, and returns JSON.
    The exception handlers registered here map core's typed exceptions to HTTP
    status codes once, so no route translates an error itself:

    * ``NotFoundError`` → 404
    * ``ConfigurationError`` → 400
    * ``JobConflictError`` → 409
    * ``PlexAPIError`` → 502
    * any other ``MusicSeedError`` → 500

    Returns:
        A FastAPI app with no URL prefix. ``server.create_ui_app`` mounts it
        at ``/api`` when a web UI is served alongside the JSON API.
    """
    app = FastAPI(title="MusicSeed API", version="0.1.0")

    # Browser protections: Host allowlist + origin check + CSRF token. Runs
    # before routing so rejected requests never reach a handler.
    @app.middleware("http")
    async def _security(request: Request, call_next):
        return await security_filter(request, call_next)

    @app.get(CSRF_ENDPOINT, tags=["security"])
    def csrf_token() -> dict:
        """Issue the browser CSRF token for state-changing requests."""
        return {"token": issue_csrf_token(get_csrf_secret())}

    # Single error contract: typed core exceptions map to HTTP status codes
    # here so route modules never translate exceptions themselves.
    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConfigurationError)
    async def _configuration(request: Request, exc: ConfigurationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(JobConflictError)
    async def _conflict(request: Request, exc: JobConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(PlexAPIError)
    async def _plex_api(request: Request, exc: PlexAPIError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(MusicSeedError)
    async def _musicseed(request: Request, exc: MusicSeedError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.include_router(discovery.router)
    app.include_router(plex_auth.router)
    app.include_router(library.router)
    app.include_router(enrichment.router)
    app.include_router(recommend.router)
    app.include_router(sonic.router)
    app.include_router(dashboard.router)
    app.include_router(jobs.router)
    app.include_router(playlists.router)
    return app


app = create_app()
