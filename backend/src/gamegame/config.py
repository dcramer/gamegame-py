"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://gamegame:gamegame@localhost:5432/gamegame",
        description="PostgreSQL connection URL with asyncpg driver",
    )
    database_url_test: str = Field(
        default="postgresql+asyncpg://gamegame_test:gamegame_test@localhost:5433/gamegame_test",
        description="Test database URL",
    )
    database_pool_size: int = Field(default=5, description="Connection pool size")
    database_max_overflow: int = Field(default=10, description="Max overflow connections")

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL for task queue",
    )

    # Auth
    session_secret: str = Field(
        default="change-this-to-a-secure-32-char-secret",
        min_length=32,
        description="Secret key for JWT signing",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiration_days: int = Field(default=30, description="JWT token expiration in days")
    magic_link_expiration_minutes: int = Field(
        default=15, description="Magic link expiration in minutes"
    )

    # OpenAI
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", description="OpenAI embedding model"
    )
    openai_chat_model: str = Field(default="gpt-4o", description="OpenAI chat model")
    openai_chat_model_dev: str = Field(
        default="gpt-4o-mini", description="OpenAI chat model for development"
    )
    openai_timeout: float = Field(default=60.0, description="OpenAI API timeout in seconds")

    # Mistral
    mistral_api_key: str = Field(default="", description="Mistral API key for PDF extraction")

    # Storage
    storage_backend: Literal["local", "s3"] = Field(
        default="local", description="Storage backend type"
    )
    storage_path: str = Field(default="./uploads", description="Local storage path")
    s3_bucket: str = Field(default="", description="S3 bucket name")
    s3_region: str = Field(default="us-east-1", description="S3 region")

    # App
    environment: Literal["development", "production", "test"] = Field(
        default="development", description="Application environment"
    )
    debug: bool | None = Field(default=None, description="Debug mode (defaults based on environment)")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="Allowed CORS origins",
    )

    # Email
    email_backend: Literal["console", "smtp", "resend"] = Field(
        default="console", description="Email backend (console for dev, smtp or resend for prod)"
    )
    email_from: str = Field(
        default="GameGame <noreply@gamegame.app>", description="From address for emails"
    )
    app_url: str = Field(
        default="http://localhost:5173", description="Frontend app URL for magic links"
    )

    # SMTP settings (when email_backend=smtp)
    smtp_host: str = Field(default="", description="SMTP server host")
    smtp_port: int = Field(default=587, description="SMTP server port")
    smtp_username: str = Field(default="", description="SMTP username")
    smtp_password: str = Field(default="", description="SMTP password")
    smtp_use_tls: bool = Field(default=True, description="Use TLS for SMTP")

    # Resend settings (when email_backend=resend)
    resend_api_key: str = Field(default="", description="Resend API key")

    # Sentry
    sentry_dsn: str = Field(default="", description="Sentry DSN for error tracking")

    # Embedding config
    embedding_dimensions: int = Field(default=1536, description="Embedding vector dimensions")
    embedding_batch_size: int = Field(default=100, description="Batch size for embedding")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == "development"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_test(self) -> bool:
        """Check if running in test mode."""
        return self.environment == "test"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_chat_model(self) -> str:
        """Get the active chat model based on environment."""
        return self.openai_chat_model if self.is_production else self.openai_chat_model_dev

    @computed_field  # type: ignore[prop-decorator]
    @property
    def debug_enabled(self) -> bool:
        """Get debug mode, defaulting based on environment if not explicitly set."""
        if self.debug is not None:
            return self.debug
        return self.is_development


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience alias
settings = get_settings()
