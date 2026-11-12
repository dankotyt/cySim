"""Document ingestion: parse, chunk, extract rules via LoRA, store metadata.

The document source content is processed in-memory and discarded: only its
metadata (and the extracted rules) are persisted.
"""
import asyncio
import hashlib
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..models.document import (
    DeleteResponse,
    Document,
    DocumentStatus,
    DocumentType,
    UploadResponse,
)
from ..repositories.document_repository import DocumentRepository
from ..repositories.security_rule_repository import SecurityRuleRepository
from ..utils.chunking import chunk_document
from ..utils.parsers import ParsedDocument, parse_file
from .document_validator import DocumentValidator
from .llm_provider import get_llm_provider
from .rule_structuring import LoRARuleStructurer

logger = get_logger(__name__)


class DocumentServiceError(Exception):
    """Base exception for document-service failures."""


class DocumentNotFoundError(DocumentServiceError):
    """Raised when a document id is unknown or belongs to another tenant."""


class ProcessingError(DocumentServiceError):
    """Raised when a document fails to parse, chunk, validate or structure."""


class DocumentService:
    """Ingest documents, extract rules via a LoRA adapter, store metadata only."""

    def __init__(
        self,
        settings: Settings | None = None,
        validator: DocumentValidator | None = None,
        security_rule_repository: SecurityRuleRepository | None = None,
        rule_structurer: LoRARuleStructurer | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = DocumentRepository()
        self.security_rule_repository = (
            security_rule_repository or SecurityRuleRepository()
        )
        self.validator = validator or DocumentValidator(self.settings)
        self.rule_structurer = rule_structurer or self._build_structurer()

    def _build_structurer(self) -> LoRARuleStructurer:
        """Build the structurer backed by the configured HTTP LLM backend."""
        provider = get_llm_provider(self.settings)
        return LoRARuleStructurer(
            llm_provider=provider, strict=self.settings.lora_strict
        )

    @staticmethod
    def _document_type(extension: str) -> DocumentType:
        mapping = {
            ".pdf": DocumentType.PDF,
            ".docx": DocumentType.DOCX,
            ".txt": DocumentType.TXT,
        }
        return mapping[extension]

    async def upload_document(
            self, session: AsyncSession, tenant_id: str, filename: str, content: bytes
    ) -> UploadResponse:
        """Parse, validate, chunk and structure a document, storing only metadata."""
        extension = Path(filename).suffix.lower()
        if extension not in self.settings.allowed_extensions:
            raise ValueError(f"Unsupported file type '{extension}'")
        if not content:
            raise ValueError("Uploaded file is empty")
        if len(content) > self.settings.max_upload_size_mb * 1024 * 1024:
            raise ValueError(f"File exceeds the maximum size of {self.settings.max_upload_size_mb} MB")

        content_hash = hashlib.sha256(content).hexdigest()
        document_id = str(uuid.uuid4())

        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            name=filename,
            content_hash=content_hash,
            size_bytes=len(content),
            rule_count=0,
            status=DocumentStatus.PROCESSING,
        )
        await self.repository.create(session, document)
        await session.flush()

        try:
            parsed: ParsedDocument = await asyncio.to_thread(parse_file, filename, content)
            document_type = self._document_type(extension)
            chunks = await asyncio.to_thread(
                chunk_document, parsed, document_id, filename, document_type, self.settings
            )
            if not chunks:
                raise ProcessingError(f"No extractable text found in document {document_id}")

            self.validator.validate(filename, content, parsed, chunks)

            logger.info(f"Starting LLM structuring for {document_id}...")
            result = await self.rule_structurer.structure(chunks, tenant_id, document_id)
            logger.info(f"LLM structuring done: {len(result.rules)} rules")

            await self.security_rule_repository.create_many(
                session, tenant_id, result.rules
            )

            document.status = DocumentStatus.PROCESSED
            document.rule_count = len(result.rules)
            await self.repository.update(session, document)
            await session.commit()

            return UploadResponse(
                document_id=document_id, filename=filename, status=document.status
            )

        except Exception as exc:
            document.status = DocumentStatus.FAILED
            await self.repository.update(session, document)
            await session.commit()
            logger.error(f"Processing failed for {document_id}: {exc}")
            raise ProcessingError(str(exc)) from exc

    async def _require_document(
        self, session: AsyncSession, document_id: str, tenant_id: str
    ) -> Document:
        document = await self.repository.get(session, document_id)
        if document is None or document.tenant_id != tenant_id:
            raise DocumentNotFoundError(f"Document not found: {document_id}")
        return document

    async def get_document(
        self, session: AsyncSession, document_id: str, tenant_id: str
    ) -> Document:
        """Return metadata for a single document."""
        return await self._require_document(session, document_id, tenant_id)

    async def delete_document(
        self, session: AsyncSession, document_id: str, tenant_id: str
    ) -> DeleteResponse:
        """Delete a document's metadata; its rules are removed via FK cascade."""
        await self._require_document(session, document_id, tenant_id)
        await self.repository.delete(session, document_id)
        logger.info("Document deleted: id=%s tenant=%s", document_id, tenant_id)
        return DeleteResponse(document_id=document_id, deleted=True)


_service: DocumentService | None = None

def get_document_service() -> DocumentService:
    """Return a lazily-initialised singleton :class:`DocumentService`."""
    global _service
    if _service is None:
        _service = DocumentService()
    return _service
