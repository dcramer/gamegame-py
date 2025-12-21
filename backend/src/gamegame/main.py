"""FastAPI application entrypoint."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from gamegame.api.middleware import RequestIDMiddleware, RequestLoggingMiddleware
from gamegame.api.router import api_router
from gamegame.config import settings
from gamegame.database import close_db
from gamegame.services.bgg import close_rate_limiter

logger = logging.getLogger(__name__)

# Initialize Sentry for error tracking
if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1 if settings.is_production else 1.0,
        profiles_sample_rate=0.1 if settings.is_production else 0.0,
        enable_tracing=True,
    )
    logger.info("Sentry initialized")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup: Database initialization is handled by Alembic migrations
    yield
    # Shutdown
    await close_rate_limiter()
    await close_db()


app = FastAPI(
    title="GameGame API",
    description="LLM-powered board game rules assistant",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug_enabled else None,
    redoc_url="/api/redoc" if settings.debug_enabled else None,
    openapi_url="/api/openapi.json" if settings.debug_enabled else None,
)

# Request ID middleware (must be added first to wrap other middleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# Include API router
app.include_router(api_router, prefix="/api")

# Serve uploaded files (PDFs, images, etc.)
uploads_dir = Path(settings.storage_path)
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# Serve static files in production (React SPA)
frontend_dist = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):  # noqa: ARG001
        """Serve React SPA for all non-API routes."""
        # Serve index.html for SPA routing
        index_path = frontend_dist / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return {"error": "Frontend not built"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "gamegame.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
    )
