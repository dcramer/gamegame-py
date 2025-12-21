"""Verification token model for magic link auth."""

from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


class VerificationToken(SQLModel, table=True):
    """Token for email verification / magic links."""

    __tablename__ = "verification_tokens"

    identifier: str = Field(primary_key=True, max_length=255, description="Email address")
    token: str = Field(index=True, max_length=255, description="Random verification token")
    expires: datetime = Field(
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        description="Token expiration time",
    )
