"""Health check endpoints."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from gamegame.api.deps import SessionDep

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def health_check():
    """Basic health check."""
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
