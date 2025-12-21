"""Upload endpoint tests."""

import pytest
from httpx import AsyncClient

from tests.conftest import AuthenticatedClient


@pytest.mark.asyncio
async def test_upload_requires_admin(authenticated_client: AuthenticatedClient):
    """Test that upload requires admin privileges."""
    response = await authenticated_client.post(
        "/api/upload",
        files={"file": ("test.png", b"fake image content", "image/png")},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upload_image(admin_client: AuthenticatedClient):
    """Test uploading an image file."""
    response = await admin_client.post(
        "/api/upload",
        params={"type": "image"},
        files={"file": ("test.png", b"fake image content", "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["url"].startswith("/uploads/images/")
    assert data["url"].endswith(".png")
    assert data["blob_key"].startswith("images/")
    assert data["size"] == len(b"fake image content")
    assert data["mime_type"] == "image/png"


@pytest.mark.asyncio
async def test_upload_pdf(admin_client: AuthenticatedClient):
    """Test uploading a PDF file."""
    response = await admin_client.post(
        "/api/upload",
        params={"type": "pdf"},
        files={"file": ("rules.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["url"].startswith("/uploads/pdfs/")
    assert data["url"].endswith(".pdf")
    assert data["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_upload_without_type(admin_client: AuthenticatedClient):
    """Test uploading without specifying type goes to uploads folder."""
    response = await admin_client.post(
        "/api/upload",
        files={"file": ("test.png", b"fake image content", "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["url"].startswith("/uploads/uploads/")


@pytest.mark.asyncio
async def test_upload_invalid_type_for_image(admin_client: AuthenticatedClient):
    """Test that uploading wrong file type for image upload fails."""
    response = await admin_client.post(
        "/api/upload",
        params={"type": "image"},
        files={"file": ("rules.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_invalid_type_for_pdf(admin_client: AuthenticatedClient):
    """Test that uploading wrong file type for pdf upload fails."""
    response = await admin_client.post(
        "/api/upload",
        params={"type": "pdf"},
        files={"file": ("test.png", b"fake image content", "image/png")},
    )
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_anonymous_denied(client: AsyncClient):
    """Test that anonymous users cannot upload."""
    response = await client.post(
        "/api/upload",
        files={"file": ("test.png", b"fake image content", "image/png")},
    )
    assert response.status_code == 401
