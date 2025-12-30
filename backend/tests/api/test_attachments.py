"""Attachment endpoint tests."""

import pytest
from httpx import AsyncClient

from gamegame.models import Attachment, Game, Resource
from tests.conftest import AuthenticatedClient


@pytest.mark.asyncio
async def test_get_attachment(client: AsyncClient, attachment: Attachment):
    """Test getting an attachment by ID."""
    response = await client.get(f"/api/attachments/{attachment.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == attachment.id
    assert data["mime_type"] == "image/png"
    assert data["page_number"] == 1


@pytest.mark.asyncio
async def test_get_attachment_not_found(client: AsyncClient):
    """Test getting a non-existent attachment."""
    response = await client.get("/api/attachments/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_attachment_anonymous_denied(client: AsyncClient, attachment: Attachment):
    """Test that anonymous users cannot update attachments."""
    response = await client.patch(
        f"/api/attachments/{attachment.id}",
        json={"description": "Hacked"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_attachment_requires_admin(
    authenticated_client: AuthenticatedClient, attachment: Attachment
):
    """Test that non-admin users cannot update attachments."""
    response = await authenticated_client.patch(
        f"/api/attachments/{attachment.id}",
        json={"description": "A diagram"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_attachment(admin_client: AuthenticatedClient, attachment: Attachment):
    """Test updating an attachment as admin."""
    response = await admin_client.patch(
        f"/api/attachments/{attachment.id}",
        json={"description": "A diagram showing setup"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["description"] == "A diagram showing setup"


@pytest.mark.asyncio
async def test_reprocess_attachment_anonymous_denied(client: AsyncClient, attachment: Attachment):
    """Test that anonymous users cannot reprocess attachments."""
    response = await client.post(f"/api/attachments/{attachment.id}/reprocess")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reprocess_attachment_requires_admin(
    authenticated_client: AuthenticatedClient, attachment: Attachment
):
    """Test that non-admin users cannot reprocess attachments."""
    response = await authenticated_client.post(f"/api/attachments/{attachment.id}/reprocess")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reprocess_attachment(admin_client: AuthenticatedClient, attachment: Attachment):
    """Test triggering attachment reprocessing."""
    # First set some analysis data
    response = await admin_client.patch(
        f"/api/attachments/{attachment.id}",
        json={"description": "Old description"},
    )
    assert response.status_code == 200

    # Then reprocess to clear it and queue analysis
    response = await admin_client.post(f"/api/attachments/{attachment.id}/reprocess")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Attachment queued for reprocessing"
    assert data["attachment"]["description"] is None


# Tests for nested attachment list endpoints


@pytest.mark.asyncio
async def test_list_resource_attachments(client: AsyncClient, resource: Resource, attachment: Attachment):
    """Test listing attachments for a resource via nested route."""
    response = await client.get(f"/api/resources/{resource.id}/attachments")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == attachment.id


@pytest.mark.asyncio
async def test_list_resource_attachments_not_found(client: AsyncClient):
    """Test listing attachments for non-existent resource."""
    response = await client.get("/api/resources/nonexistent/attachments")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_game_attachments(
    admin_client: AuthenticatedClient, game: Game, attachment: Attachment
):
    """Test listing attachments for a game via nested route. Requires admin."""
    response = await admin_client.get(f"/api/games/{game.id}/attachments")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == attachment.id


@pytest.mark.asyncio
async def test_list_game_attachments_by_slug(
    admin_client: AuthenticatedClient, game: Game, attachment: Attachment
):
    """Test listing attachments for a game by slug. Requires admin."""
    response = await admin_client.get(f"/api/games/{game.slug}/attachments")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == attachment.id


@pytest.mark.asyncio
async def test_list_game_attachments_not_found(admin_client: AuthenticatedClient):
    """Test listing attachments for non-existent game."""
    response = await admin_client.get("/api/games/nonexistent/attachments")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_game_attachments_requires_admin(client: AsyncClient, game: Game):
    """Test that listing game attachments requires admin auth."""
    response = await client.get(f"/api/games/{game.id}/attachments")
    assert response.status_code == 401
