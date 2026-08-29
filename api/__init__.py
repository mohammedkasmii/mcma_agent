"""
api package — HTTP layer.

Translates HTTP into calls on db/, portal/ and workflows/. Contains no business
logic of its own.

Routers:
    system    /health, /api/v1/features
    state     /api/v1/state, /api/v1/employee-actions      (the operations hub)
    accounts  /api/v1/accounts/*, /api/v1/refresh
    filling   /api/v1/fill-*, /api/v1/map-wexia-dossier    (Phase 2, disabled)

Removed in the Phase 1 cleanup — these wrote to logs/*.json, a second store that
silently diverged from SQLite after the migration:
    GET/POST /api/v1/notification-actions   -> POST /api/v1/employee-actions
    GET      /api/v1/cached-notifications   -> GET  /api/v1/state
    GET      /api/v1/notifications          -> POST /api/v1/refresh
    POST     /api/v1/auth/launch-login      -> POST /api/v1/accounts/{id}/login
"""

import contextlib
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api import accounts, filling, state, system
from api.deps import get_repo, start_poller, stop_poller

STATIC_DIR = "static"


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Opens the database and starts the poller; stops both cleanly on shutdown."""
    get_repo()
    await start_poller()
    yield
    await stop_poller()


def create_app() -> FastAPI:
    """Builds the application. Kept as a factory so tests can construct it freely."""
    app = FastAPI(
        title="MCMA Operations Hub",
        description=(
            "Multi-account notification hub for the MAMDA/MCMA portal. "
            "Phase 2 form filling is present but disabled."
        ),
        version="3.0.0",
        lifespan=lifespan,
    )

    app.include_router(system.router)
    app.include_router(state.router)
    app.include_router(accounts.router)
    app.include_router(filling.router)

    # Mounted last: it claims "/" and would shadow the API routes otherwise.
    if os.path.isdir(STATIC_DIR):
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


__all__ = ["create_app", "lifespan"]
