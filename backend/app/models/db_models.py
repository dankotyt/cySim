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


class SecurityRuleORM(Base):
    """Structured security rule produced by LLM structuring."""

    __tablename__ = "security_rules"
    __table_args__ = (
        Index("idx_security_rules_tenant_id", "tenant_id"),
        Index("idx_security_rules_document_id", "document_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255))
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    audience: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
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
    """Training scenario generated from security rules."""

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), index=True)
    rule_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("security_rules.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255))
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    step_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    actions: Mapped[list] = mapped_column(JSON, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    scoring: Mapped[dict] = mapped_column(JSON, nullable=False)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
