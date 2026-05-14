"""FastAPI entrypoint.

Feature 01 provided a stub with /health only. Feature 17 adds
the full API surface (ingest, meter status, inspection queue, feedback).
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.api.ai import router as ai_router
from app.api.routes import router as api_router
from app.demo_seed import start_demo_seed_if_enabled

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="AT&C Loss Recovery Intelligence System - prototype API.",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    # Comma-separated; set CORS_ORIGINS to the deployed dashboard URL in production.
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes from Feature 17
app.include_router(api_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")


@app.on_event("startup")
def _demo_seed() -> None:
    start_demo_seed_if_enabled()


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness probe. Does not touch the database."""
    return {"status": "ok", "service": settings.app_name, "version": __version__}
