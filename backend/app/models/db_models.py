"""SQLAlchemy ORM models for PostgreSQL persistence.

These mirror the Pydantic models in :mod:`app.models.document` but stay
independent of them: the repository layer is responsible for translating
between ORM rows and Pydantic DTOs.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class DocumentORM(Base):
    """Persisted metadata record for an ingested document.

    Only metadata is stored: the source content and its chunks are processed
    in-memory and discarded, never persisted.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_tenant_id", "tenant_id"),
        Index("idx_documents_status", "status"),
        Index("idx_documents_tenant_deleted", "tenant_id", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    rule_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SecurityRuleORM(Base):
    """Structured security rule produced by LLM structuring."""

    __tablename__ = "security_rules"
    __table_args__ = (
        Index("idx_security_rules_tenant_id", "tenant_id"),
        Index("idx_security_rules_document_id", "document_id"),
        Index("idx_security_rules_tenant_content_hash", "tenant_id", "content_hash"),
        Index("idx_security_rules_tenant_deleted", "tenant_id", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255))
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    audience: Mapped[list] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DepartmentORM(Base):
    """Organisational unit with a topic allowlist."""

    __tablename__ = "departments"
    __table_args__ = (
        Index("idx_departments_tenant_id", "tenant_id"),
        UniqueConstraint(
            "tenant_id", "name", name="uq_departments_tenant_name"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_topics: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ScenarioORM(Base):
    """A generated room scenario.

    ``room`` is the whole contract document (objects, goal, brief, difficulty);
    the scalar columns beside it exist for filtering and analytics only.
    """

    __tablename__ = "scenarios"
    __table_args__ = (
        Index("idx_scenarios_tenant_deleted", "tenant_id", "deleted_at"),
        Index("idx_scenarios_tenant_fingerprint", "tenant_id", "fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    topic: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    room: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    max_points: Mapped[int] = mapped_column(Integer, default=0)
    diff: Mapped[int] = mapped_column(Integer, default=1)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    corpus_build_id: Mapped[str] = mapped_column(String(64), default="")
    rule_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="generated")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ScenarioAttemptORM(Base):
    """One trainee attempt at a room, stored as an event log.

    The outcome and score are denormalised for analytics; the log stays the
    source of truth and the engine can always re-evaluate it.
    """

    __tablename__ = "scenario_attempts"
    __table_args__ = (
        Index("idx_scenario_attempts_tenant_employee", "tenant_id", "employee_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[str] = mapped_column(String(255), nullable=False)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    outcome: Mapped[str] = mapped_column(String(16), default="in_progress")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_points: Mapped[int] = mapped_column(Integer, nullable=False)
    lessons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
