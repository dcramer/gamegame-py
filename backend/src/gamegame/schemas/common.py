"""Common schemas used across the API."""

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Pagination query parameters."""

    offset: int = Field(default=0, ge=0, description="Number of items to skip")
    limit: int = Field(default=20, ge=1, le=100, description="Number of items to return")


class PaginatedResponse[T](BaseModel):
    """Paginated response wrapper."""

    items: list[T]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        """Check if there are more items."""
        return self.offset + len(self.items) < self.total


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    code: str | None = None


class SuccessResponse(BaseModel):
    """Standard success response."""

    message: str
