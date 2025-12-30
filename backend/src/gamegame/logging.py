"""Logging configuration based on environment."""

import logging
import sys

from gamegame.config import settings

# Development format: cleaner
DEV_FORMAT = "%(levelname)s:     %(name)s - %(message)s"

# Production format: full details for debugging
PROD_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_uvicorn_log_config() -> dict:
    """Get uvicorn log config based on environment."""
    is_dev = settings.is_development

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "access": {
                # Use uvicorn's custom formatter with appropriate format
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s "%(request_line)s" %(status_code)s' if is_dev
                else '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s" if is_dev else "%(asctime)s %(levelprefix)s %(message)s",
            },
        },
        "handlers": {
            "access": {
                "class": "logging.StreamHandler",
                "formatter": "access",
                "stream": "ext://sys.stdout",
            },
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn.access": {
                "handlers": ["access"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["default"],
                "level": "INFO",
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["default"],
            "level": settings.log_level,
        },
    }


def setup_logging() -> None:
    """Configure logging for the application."""
    is_dev = settings.is_development
    log_format = DEV_FORMAT if is_dev else PROD_FORMAT

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format=log_format,
        stream=sys.stdout,
    )

    # Quiet noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
