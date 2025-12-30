"""FastAPI application entrypoint."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from gamegame.api.middleware import RequestIDMiddleware
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

# Request ID middleware for distributed tracing
app.add_middleware(RequestIDMiddleware)  # type: ignore[arg-type]

# CORS middleware
app.add_middleware(
    CORSMiddleware,  # type: ignore[arg-type]
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
# Note: In development, Vite handles SPA routing; this is only for production builds
frontend_dist = Path(__file__).parent.parent.parent.parent / "frontend" / "build" / "client"
if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    from fastapi import Request
    from fastapi.responses import FileResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.exception_handler(404)
    async def spa_404_handler(request: Request, _exc: StarletteHTTPException):
        """Serve SPA for 404s that aren't API/uploads/assets requests."""
        path = request.url.path
        # Don't serve SPA for API, uploads, or assets - return actual 404
        if path.startswith(("/api", "/uploads", "/assets")):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Not found"}, status_code=404)

        # Serve index.html for SPA client-side routing
        return FileResponse(frontend_dist / "index.html")


if __name__ == "__main__":
    import uvicorn

    from gamegame.logging import get_uvicorn_log_config

    uvicorn.run(
        "gamegame.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_config=get_uvicorn_log_config(),
    )
