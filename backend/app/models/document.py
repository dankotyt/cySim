"""Pydantic models for documents, chunks and search results."""
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


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
    tenant_id: str = "default"


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
    tenant_id: str = "default"
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
    """A structured security rule extracted from retrieved chunks."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    category: str = "general"
    source: str
    page: int
    score: float
    created_at: datetime = Field(default_factory=_utcnow)


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
