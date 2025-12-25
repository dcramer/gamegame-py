"""Health check endpoints."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from gamegame.api.deps import SessionDep
from gamegame.config import settings
from gamegame.tasks.queue import queue

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def health_check():
    """Basic health check - just confirms the service is running."""
    return {"status": "ok"}


@router.get("/db")
async def health_check_db(session: SessionDep):
    """Health check with database connectivity."""
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error(f"Database health check failed: {e!r}")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "disconnected"},
        )


@router.get("/redis")
async def health_check_redis():
    """Health check for Redis connectivity (task queue)."""
    try:
        redis = queue.redis  # type: ignore[attr-defined]
        if redis is None:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "redis": "not_initialized"},
            )
        await redis.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception as e:
        logger.error(f"Redis health check failed: {e!r}")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "redis": "disconnected"},
        )


@router.get("/ready")
async def readiness_check(session: SessionDep):
    """Readiness check - confirms all dependencies are available.

    Use this endpoint for Kubernetes readiness probes or load balancer health checks.
    Returns 503 if any critical dependency is unavailable.
    """
    errors = {}

    # Check database
    try:
        await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database readiness check failed: {e!r}")
        db_status = "disconnected"
        errors["database"] = str(e)

    # Check Redis
    try:
        redis = queue.redis  # type: ignore[attr-defined]
        if redis is None:
            redis_status = "not_initialized"
            errors["redis"] = "Redis client not initialized"
        else:
            await redis.ping()
            redis_status = "connected"
    except Exception as e:
        logger.error(f"Redis readiness check failed: {e!r}")
        redis_status = "disconnected"
        errors["redis"] = str(e)

    # Check required API keys are configured
    api_keys_ok = bool(settings.openai_api_key and settings.mistral_api_key)

    status = "ok" if not errors and api_keys_ok else "degraded"
    response = {
        "status": status,
        "database": db_status,
        "redis": redis_status,
        "api_keys_configured": api_keys_ok,
    }

    if errors:
        return JSONResponse(status_code=503, content=response)
    return response
