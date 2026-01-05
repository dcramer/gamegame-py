"""Main API router that aggregates all route modules."""

from fastapi import APIRouter

from gamegame.api import (
    attachments,
    auth,
    bgg,
    chat,
    games,
    health,
    resources,
    search,
    segments,
    upload,
    workflows,
)

api_router = APIRouter()

# Include all route modules
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(games.router, prefix="/games", tags=["games"])
api_router.include_router(bgg.router, prefix="/bgg", tags=["bgg"])

# Resources - nested under games and standalone
api_router.include_router(
    resources.game_resources_router,
    prefix="/games/{game_id_or_slug}/resources",
    tags=["resources"],
)
api_router.include_router(resources.router, prefix="/resources", tags=["resources"])

# Attachments - standalone and nested routes
api_router.include_router(attachments.router, prefix="/attachments", tags=["attachments"])
api_router.include_router(
    attachments.resource_attachments_router,
    prefix="/resources/{resource_id}/attachments",
    tags=["attachments"],
)
api_router.include_router(
    attachments.game_attachments_router,
    prefix="/games/{game_id_or_slug}/attachments",
    tags=["attachments"],
)

# Segments
api_router.include_router(segments.router, prefix="/segments", tags=["segments"])

# Upload
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])

# Search
api_router.include_router(search.router, prefix="/search", tags=["search"])

# Chat - nested under games
api_router.include_router(chat.router, prefix="/games", tags=["chat"])

# Admin endpoints
api_router.include_router(workflows.router, prefix="/admin/workflows", tags=["admin"])
