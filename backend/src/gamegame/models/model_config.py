"""Model Configuration.

Centralizes model selection across the application.
Uses environment variables to switch between dev (cheap) and prod (quality) models.
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Environment(str, Enum):
    """Application environment."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


@dataclass
class ModelConfig:
    """Model configuration for different tasks."""

    # Model for OCR text extraction
    ocr: Literal["mistral"] = "mistral"
    # Model for vision/image analysis
    vision: str = "gpt-5-mini"
    # Model for text reasoning (cleanup, metadata, etc.)
    reasoning: str = "gpt-5-mini"
    # Model for intent/answer-type classification
    classification: str = "gpt-5-mini"
    # Model for synthetic question generation (HyDE)
    hyde: str = "gpt-5-mini"
    # Model for search result reranking
    reranking: str = "gpt-5-mini"
    # Model for embeddings
    embedding: str = "text-embedding-3-small"

    # Max chars per chunk for cleanup stage
    # Smaller chunks = faster responses = less likely to timeout
    # 20k chars processes ~2-3 pages per API call
    cleanup_chunk_size: int = 20_000


# Development/Test models - optimized for cost and speed
DEV_MODELS = ModelConfig(
    ocr="mistral",
    vision="gpt-5-mini",
    reasoning="gpt-5-mini",
    classification="gpt-5-mini",
    hyde="gpt-5-mini",
    reranking="gpt-5-mini",
    embedding="text-embedding-3-small",
)

# Production models - optimized for quality
PROD_MODELS = ModelConfig(
    ocr="mistral",
    vision="gpt-5",
    reasoning="gpt-5",
    classification="gpt-5-mini",
    hyde="gpt-5",
    reranking="gpt-5-mini",
    embedding="text-embedding-3-small",
)


def get_environment(env_var: str | None = None) -> Environment:
    """Get the current environment from env variable."""
    env = (env_var or os.environ.get("ENVIRONMENT", "development")).lower()

    if env in ("production", "prod"):
        return Environment.PRODUCTION

    if env == "test":
        return Environment.TEST

    return Environment.DEVELOPMENT


def get_model_config(environment: str | None = None) -> ModelConfig:
    """Get model configuration based on environment."""
    env = get_environment(environment)

    # Test and development use the same cheap models
    if env in (Environment.DEVELOPMENT, Environment.TEST):
        return DEV_MODELS

    return PROD_MODELS


def get_model(task: str, environment: str | None = None) -> str:
    """Get a specific model for a task.

    Args:
        task: One of: ocr, vision, reasoning, classification, hyde, reranking, embedding
        environment: Optional environment override

    Returns:
        Model name string
    """
    config = get_model_config(environment)
    return getattr(config, task)
