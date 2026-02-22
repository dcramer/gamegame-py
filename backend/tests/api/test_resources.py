"""Resource endpoint tests."""

import pytest
from httpx import AsyncClient

from gamegame.models import Game, Resource
from tests.conftest import AuthenticatedClient


@pytest.mark.asyncio
async def test_list_resources_empty(client: AsyncClient, game: Game):
    """Test listing resources when none exist."""
    response = await client.get(f"/api/games/{game.id}/resources")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_resources_by_game_id(client: AsyncClient, resource: Resource, game: Game):
    """Test listing resources by game ID."""
    response = await client.get(f"/api/games/{game.id}/resources")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Rulebook"
    assert data[0]["fragment_count"] == 0


@pytest.mark.asyncio
async def test_list_resources_by_game_slug(client: AsyncClient, resource: Resource, game: Game):
    """Test listing resources by game slug."""
    response = await client.get(f"/api/games/{game.slug}/resources")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Rulebook"


@pytest.mark.asyncio
async def test_list_resources_game_not_found(client: AsyncClient):
    """Test listing resources for non-existent game."""
    response = await client.get("/api/games/nonexistent/resources")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_resource(client: AsyncClient, resource: Resource):
    """Test getting a resource by ID."""
    response = await client.get(f"/api/resources/{resource.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Rulebook"
    assert data["status"] == "completed"
    assert data["fragment_count"] == 0


@pytest.mark.asyncio
async def test_get_resource_not_found(client: AsyncClient):
    """Test getting a non-existent resource."""
    response = await client.get("/api/resources/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_resource_anonymous_denied(client: AsyncClient, resource: Resource):
    """Test that anonymous users cannot update resources."""
    response = await client.patch(f"/api/resources/{resource.id}", json={"name": "Hacked"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_resource_requires_admin(
    authenticated_client: AuthenticatedClient, resource: Resource
):
    """Test that non-admin users cannot update resources."""
    response = await authenticated_client.patch(
        f"/api/resources/{resource.id}",
        json={"name": "Updated Name"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_resource(admin_client: AuthenticatedClient, resource: Resource):
    """Test updating a resource as admin."""
    response = await admin_client.patch(
        f"/api/resources/{resource.id}",
        json={"name": "Updated Rulebook"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Rulebook"


@pytest.mark.asyncio
async def test_delete_resource_anonymous_denied(client: AsyncClient, resource: Resource):
    """Test that anonymous users cannot delete resources."""
    response = await client.delete(f"/api/resources/{resource.id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_resource_requires_admin(
    authenticated_client: AuthenticatedClient, resource: Resource
):
    """Test that non-admin users cannot delete resources."""
    response = await authenticated_client.delete(f"/api/resources/{resource.id}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_resource(admin_client: AuthenticatedClient, resource: Resource):
    """Test deleting a resource as admin."""
    response = await admin_client.delete(f"/api/resources/{resource.id}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_reprocess_resource_anonymous_denied(client: AsyncClient, resource: Resource):
    """Test that anonymous users cannot reprocess resources."""
    response = await client.post(f"/api/resources/{resource.id}/reprocess")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reprocess_resource(admin_client: AuthenticatedClient, resource: Resource):
    """Test triggering resource reprocessing."""
    response = await admin_client.post(f"/api/resources/{resource.id}/reprocess")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_reprocess_resource_invalid_stage(admin_client: AuthenticatedClient, resource: Resource):
    """Invalid start_stage values should fail validation."""
    response = await admin_client.post(
        f"/api/resources/{resource.id}/reprocess",
        params={"start_stage": "not-a-stage"},
    )
    assert response.status_code == 422


# --- Upload Resource Tests ---


@pytest.mark.asyncio
async def test_upload_resource_anonymous_denied(client: AsyncClient, game: Game, pdf_content: bytes):
    """Test that anonymous users cannot upload resources."""
    response = await client.post(
        f"/api/games/{game.id}/resources",
        files={"file": ("rulebook.pdf", pdf_content, "application/pdf")},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_resource_requires_admin(
    authenticated_client: AuthenticatedClient, game: Game, pdf_content: bytes
):
    """Test that non-admin users cannot upload resources."""
    response = await authenticated_client.post(
        f"/api/games/{game.id}/resources",
        files={"file": ("rulebook.pdf", pdf_content, "application/pdf")},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upload_resource(admin_client: AuthenticatedClient, game: Game, pdf_content: bytes):
    """Test uploading a PDF resource as admin."""
    response = await admin_client.post(
        f"/api/games/{game.id}/resources",
        files={"file": ("Test-Rulebook.pdf", pdf_content, "application/pdf")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Rulebook"  # Derived from filename
    assert data["original_filename"] == "Test-Rulebook.pdf"
    assert data["status"] == "queued"
    assert data["resource_type"] == "rulebook"
    assert data["game_id"] == game.id
    assert data["url"].startswith("/uploads/pdfs/")
    assert data["fragment_count"] == 0


@pytest.mark.asyncio
async def test_upload_resource_invalid_file_type(admin_client: AuthenticatedClient, game: Game):
    """Test that uploading non-PDF files is rejected."""
    response = await admin_client.post(
        f"/api/games/{game.id}/resources",
        files={"file": ("image.png", b"fake image content", "image/png")},
    )
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_resource_game_not_found(admin_client: AuthenticatedClient, pdf_content: bytes):
    """Test uploading to non-existent game."""
    response = await admin_client.post(
        "/api/games/nonexistent-game/resources",
        files={"file": ("rulebook.pdf", pdf_content, "application/pdf")},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_resource_by_slug(admin_client: AuthenticatedClient, game: Game, pdf_content: bytes):
    """Test uploading a resource using game slug."""
    response = await admin_client.post(
        f"/api/games/{game.slug}/resources",
        files={"file": ("rules.pdf", pdf_content, "application/pdf")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["game_id"] == game.id
