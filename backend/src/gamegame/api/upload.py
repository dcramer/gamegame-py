"""File upload endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from gamegame.api.deps import AdminUser
from gamegame.services.storage import storage

router = APIRouter()

# Max file sizes
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_PDF_SIZE = 100 * 1024 * 1024  # 100MB


class UploadResponse(BaseModel):
    """Response from file upload."""

    url: str
    blob_key: str
    size: int
    mime_type: str


def get_extension(content_type: str, filename: str | None) -> str:
    """Get file extension from content type or filename."""
    # Try to get from filename first
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()

    # Fall back to content type mapping
    mime_to_ext = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "application/pdf": "pdf",
    }
    return mime_to_ext.get(content_type, "bin")


@router.post("", response_model=UploadResponse)
async def upload_file(
    _user: AdminUser,
    file: Annotated[UploadFile, File()],
    upload_type: Annotated[Literal["image", "pdf"] | None, Query(alias="type")] = None,
):
    """Upload a file (admin only).

    Query parameters:
        type: 'image' (10MB max) or 'pdf' (100MB max)
    """
    # Determine max size based on type
    if upload_type == "image":
        max_size = MAX_IMAGE_SIZE
        allowed_types = {"image/png", "image/jpeg", "image/gif", "image/webp"}
        prefix = "images"
    elif upload_type == "pdf":
        max_size = MAX_PDF_SIZE
        allowed_types = {"application/pdf"}
        prefix = "pdfs"
    else:
        max_size = MAX_PDF_SIZE
        allowed_types = {
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "application/pdf",
        }
        prefix = "uploads"

    # Validate content type
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type: {file.content_type}. Allowed: {', '.join(allowed_types)}",
        )

    # Read file content
    content = await file.read()

    # Validate size
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {max_size // (1024 * 1024)}MB",
        )

    # Get extension
    extension = get_extension(file.content_type or "", file.filename)

    # Upload to storage
    url, blob_key = await storage.upload_file(
        data=content,
        prefix=prefix,
        extension=extension,
    )

    return UploadResponse(
        url=url,
        blob_key=blob_key,
        size=len(content),
        mime_type=file.content_type or "application/octet-stream",
    )
