"""SQLModel database models."""

from gamegame.models.attachment import Attachment
from gamegame.models.base import BaseModel, TimestampMixin
from gamegame.models.bgg_game import BGGGame, is_cache_stale
from gamegame.models.embedding import Embedding
from gamegame.models.fragment import Fragment
from gamegame.models.game import Game
from gamegame.models.resource import Resource, ResourceStatus, ResourceType
from gamegame.models.segment import Segment
from gamegame.models.user import User
from gamegame.models.verification_token import VerificationToken
from gamegame.models.workflow_run import WorkflowRun, WorkflowStatus

__all__ = [
    "Attachment",
    "BGGGame",
    "BaseModel",
    "Embedding",
    "Fragment",
    "Game",
    "Resource",
    "ResourceStatus",
    "ResourceType",
    "Segment",
    "TimestampMixin",
    "User",
    "VerificationToken",
    "WorkflowRun",
    "WorkflowStatus",
    "is_cache_stale",
]
