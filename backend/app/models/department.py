"""Pydantic models for departments and their topic allowlists."""
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return the current UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc)


class Department(BaseModel):
    """An organisational unit with a list of allowed rule topics."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    name: str
    allowed_topics: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
