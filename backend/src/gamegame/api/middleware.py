"""API middleware for cross-cutting concerns."""

import logging
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Context variable for request ID - accessible from anywhere in the request
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Get the current request ID from context.

    Can be called from anywhere during request processing to get the
    correlation ID for logging.
    """
    return request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that adds a unique request ID to each request.

    - Checks for incoming X-Request-ID header (for distributed tracing)
    - Generates a new UUID if not present
    - Adds the request ID to the response headers
    - Stores it in a context variable for logging
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Store in context variable for access in other code
        token = request_id_var.set(request_id)

        try:
            # Process request
            response = await call_next(request)

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # Reset context variable
            request_id_var.reset(token)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs request details with timing."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = get_request_id() or "-"
        start_time = time.perf_counter()

        # Log request start
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} started",
            extra={"request_id": request_id},
        )

        try:
            response = await call_next(request)

            # Log request completion
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"[{request_id}] {request.method} {request.url.path} "
                f"completed {response.status_code} in {duration_ms:.1f}ms",
                extra={
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"[{request_id}] {request.method} {request.url.path} "
                f"failed after {duration_ms:.1f}ms: {e}",
                extra={
                    "request_id": request_id,
                    "duration_ms": duration_ms,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise


class RequestContextFilter(logging.Filter):
    """Logging filter that adds request_id to all log records.

    Usage:
        handler = logging.StreamHandler()
        handler.addFilter(RequestContextFilter())
        formatter = logging.Formatter('%(asctime)s [%(request_id)s] %(message)s')
        handler.setFormatter(formatter)
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True
