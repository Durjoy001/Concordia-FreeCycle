"""FastAPI application factory."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import agent, auth, claims, listings, notifications, wishlist
from app.services.exceptions import ServiceError

logger = logging.getLogger("freecycle")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Concordia FreeCycle API",
        version="0.1.0",
        description="Give away and claim free student items, with an agentic AI core.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ServiceError)
    async def _service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
        """Single translation point from domain errors to HTTP responses."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        settings.public_upload_base_url,
        StaticFiles(directory=settings.upload_dir),
        name="uploads",
    )

    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(listings.router, prefix=settings.api_prefix)
    app.include_router(claims.listing_claims_router, prefix=settings.api_prefix)
    app.include_router(claims.claims_router, prefix=settings.api_prefix)
    app.include_router(wishlist.router, prefix=settings.api_prefix)
    app.include_router(notifications.router, prefix=settings.api_prefix)
    app.include_router(agent.router, prefix=settings.api_prefix)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, Any]:
        return {"status": "ok", "agent_configured": settings.agent_configured}

    return app


app = create_app()
