"""File storage service for local filesystem and cloud storage."""

import uuid
from pathlib import Path

import aiofiles
import aiofiles.os

from gamegame.config import settings


class StorageService:
    """Service for file storage operations."""

    def __init__(self) -> None:
        """Initialize storage service."""
        self.upload_dir = Path(settings.storage_path)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def _generate_key(self, prefix: str, extension: str) -> str:
        """Generate a unique storage key."""
        unique_id = uuid.uuid4().hex[:12]
        return f"{prefix}/{unique_id}.{extension}"

    async def upload_file(
        self,
        data: bytes,
        prefix: str,
        extension: str,
        _filename: str | None = None,  # Reserved for future use (e.g., logging)
    ) -> tuple[str, str]:
        """Upload a file and return (url, key).

        Args:
            data: File content as bytes
            prefix: Path prefix (e.g., "resources/123/attachments")
            extension: File extension without dot (e.g., "pdf", "png")
            filename: Optional original filename for reference

        Returns:
            Tuple of (public_url, storage_key)
        """
        key = self._generate_key(prefix, extension)
        file_path = self.upload_dir / key

        # Create parent directories (sync is OK here - just creates dirs)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file asynchronously
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(data)

        # Return URL (for local storage, just the path)
        url = f"/uploads/{key}"

        return url, key

    async def delete_file(self, key: str) -> bool:
        """Delete a file by key.

        Returns True if file was deleted, False if not found.
        """
        file_path = self.upload_dir / key
        if await aiofiles.os.path.exists(file_path):
            await aiofiles.os.remove(file_path)
            return True
        return False

    async def get_file(self, key: str) -> bytes | None:
        """Get file contents by key."""
        file_path = self.upload_dir / key
        if await aiofiles.os.path.exists(file_path):
            async with aiofiles.open(file_path, "rb") as f:
                return await f.read()
        return None

    async def file_exists(self, key: str) -> bool:
        """Check if a file exists."""
        file_path = self.upload_dir / key
        return await aiofiles.os.path.exists(file_path)

    async def list_files(self, prefix: str = "") -> list[str]:
        """List all files under a prefix.

        Args:
            prefix: Optional prefix to filter by (e.g., "resources/")

        Returns:
            List of storage keys
        """
        import os

        keys: list[str] = []
        base_path = self.upload_dir / prefix if prefix else self.upload_dir

        if not base_path.exists():
            return keys

        # Walk the directory tree
        for root, _dirs, files in os.walk(base_path):
            for filename in files:
                file_path = Path(root) / filename
                # Get relative path from upload_dir
                key = str(file_path.relative_to(self.upload_dir))
                keys.append(key)

        return keys


# Global storage service instance
storage = StorageService()
