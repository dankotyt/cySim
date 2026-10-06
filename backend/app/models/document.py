"""Pydantic models for documents, chunks and search results."""
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from ..core.config import DEFAULT_TENANT_ID
from ..core.topics import ALLOWED_TOPICS


def _utcnow() -> datetime:
    """Return the current UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc)


class DocumentStatus(str, Enum):
    """Lifecycle state of an uploaded document."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class DocumentType(str, Enum):
    """Supported source document formats."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"


class Document(BaseModel):
    """Metadata record describing a stored document."""

    id: str
    tenant_id: str
    filename: str
    document_type: DocumentType
    status: DocumentStatus = DocumentStatus.UPLOADED
    file_path: str
    size_bytes: int = 0
    page_count: int = 0
    chunk_count: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    processed_at: datetime | None = None


class UploadResponse(BaseModel):
    """Result of a successful upload."""

    document_id: str
    filename: str
    status: DocumentStatus


class ProcessRequest(BaseModel):
    """Request body for triggering document processing."""

    document_id: str
    tenant_id: str = DEFAULT_TENANT_ID


class ProcessResponse(BaseModel):
    """Result of a document processing run."""

    document_id: str
    status: DocumentStatus
    chunks_created: int = 0
    pages_parsed: int = 0


class Chunk(BaseModel):
    """A single semantic chunk with its provenance metadata."""

    id: str
    document_id: str
    text: str
    page: int
    chunk_index: int
    source: str
    document_type: DocumentType


class SearchQuery(BaseModel):
    """Request model for semantic search."""

    query: str
    tenant_id: str = DEFAULT_TENANT_ID
    top_k: int = 5
    filename: str | None = None
    document_type: DocumentType | None = None


class SearchResult(BaseModel):
    """A single retrieved chunk."""

    document_id: str
    text: str
    source: str
    page: int
    score: float


class SearchResponse(BaseModel):
    """A list of retrieved chunks for a query."""

    query: str
    results: list[SearchResult]
    message: str | None = None


class SecurityRule(BaseModel):
    """A structured security rule produced by LLM structuring of document chunks."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    section: str
    topic: str
    linked_docs: list[str] = Field(default_factory=list)
    document_id: str
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("topic")
    @classmethod
    def _validate_topic(cls, value: str) -> str:
        """Reject topics outside the controlled vocabulary."""
        if value not in ALLOWED_TOPICS:
            raise ValueError(
                f"Invalid topic {value!r}; allowed: {ALLOWED_TOPICS}"
            )
        return value


class MissingReference(BaseModel):
    """An internal document referenced by a rule but not yet uploaded."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    document_id: str
    reference: str
    section: str
    created_at: datetime = Field(default_factory=_utcnow)


class MissingReferencesClearResponse(BaseModel):
    """Result of clearing missing references for a tenant."""

    deleted: int


class DeleteResponse(BaseModel):
    """Result of a document deletion."""

    document_id: str
    deleted: bool


class MetricsResponse(BaseModel):
    """Aggregated processing metrics."""

    documents_processed: int
    documents_failed: int
    total_chunks: int
    average_processing_seconds: float
