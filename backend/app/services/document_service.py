"""Document ingestion, parsing, chunking, storage and retrieval."""
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..models.document import (
    DeleteResponse,
    Document,
    DocumentStatus,
    DocumentType,
    MetricsResponse,
    MissingReference,
    ProcessResponse,
    SearchResponse,
    SearchResult,
    SecurityRule,
    UploadResponse,
)
from ..models.db_models import DocumentORM
from ..repositories.document_chunk_repository import DocumentChunkRepository
from ..repositories.document_repository import DocumentRepository
from ..repositories.missing_reference_repository import MissingReferenceRepository
from ..repositories.security_rule_repository import SecurityRuleRepository
from ..utils.chunking import chunk_document
from ..utils.embeddings import EmbeddingProvider, get_embedding_provider
from ..utils.parsers import ParsedDocument, parse_file
from .document_validator import DocumentValidationError, DocumentValidator
from .llm_provider import get_llm_provider
from .rule_structurer import RuleStructurer

logger = get_logger(__name__)


class DocumentServiceError(Exception):
    """Base exception for document-service failures."""


class DocumentNotFoundError(DocumentServiceError):
    """Raised when a document id is unknown or belongs to another tenant."""


class ProcessingError(DocumentServiceError):
    """Raised when a document fails to parse, chunk, validate or structure."""


class DocumentService:
    """Facade exposing the full document analysis pipeline.

    The service owns ingestion, parsing, chunking, chunk persistence, rule
    structuring and chunk retrieval. Chunks are stored in Postgres
    (``document_chunks``) and searched via ``pg_trgm`` similarity; there is no
    external vector store.

    Database access is asynchronous; each method receives an
    :class:`AsyncSession` (injected by FastAPI through ``Depends(get_db)``).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        validator: DocumentValidator | None = None,
        security_rule_repository: SecurityRuleRepository | None = None,
        rule_structurer: RuleStructurer | None = None,
        missing_reference_repository: MissingReferenceRepository | None = None,
        document_chunk_repository: DocumentChunkRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

        self.repository = DocumentRepository()
        self.security_rule_repository = (
            security_rule_repository or SecurityRuleRepository()
        )
        self.missing_reference_repository = (
            missing_reference_repository or MissingReferenceRepository()
        )
        self.document_chunk_repository = (
            document_chunk_repository or DocumentChunkRepository()
        )
        self.embedding_provider = embedding_provider or get_embedding_provider(self.settings)
        self.validator = validator or DocumentValidator(self.settings, self.embedding_provider)
        self.rule_structurer = rule_structurer or RuleStructurer(
            llm_provider=get_llm_provider(self.settings),
            embedding_provider=self.embedding_provider,
            batch_size=self.settings.rule_structuring_batch_size,
            num_ctx=self.settings.llm_num_ctx,
            dedup_threshold=self.settings.rule_dedup_threshold,
        )

        self._metrics = {
            "processed": 0,
            "failed": 0,
            "total_chunks": 0,
            "total_time": 0.0,
        }

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _document_type(extension: str) -> DocumentType:
        mapping = {
            ".pdf": DocumentType.PDF,
            ".docx": DocumentType.DOCX,
            ".txt": DocumentType.TXT,
        }
        return mapping[extension]

    async def _require_document(
        self, session: AsyncSession, document_id: str, tenant_id: str
    ) -> Document:
        document = await self.repository.get(session, document_id)
        if document is None or document.tenant_id != tenant_id:
            raise DocumentNotFoundError(f"Document not found: {document_id}")
        return document

    def _move_to_quarantine(self, document: Document) -> None:
        """Move the original file into the quarantine directory."""
        source = Path(document.file_path)
        if not source.exists():
            return
        target_dir = self.settings.quarantine_dir / document.tenant_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{document.id}_{document.filename}"
        shutil.move(str(source), str(target))
        document.file_path = str(target)

    async def _mark_failed(
        self,
        session: AsyncSession,
        document: Document,
        error: Exception,
        *,
        quarantine: bool = False,
    ) -> None:
        """Persist the ``FAILED`` state and (optionally) quarantine the file.

        The failure state is committed explicitly so it survives the exception
        that the service re-raises afterwards (the request dependency rolls back
        on error).
        """
        if quarantine:
            self._move_to_quarantine(document)
        document.status = DocumentStatus.FAILED
        document.error = str(error)
        await self.repository.update(session, document)
        await session.commit()
        self._metrics["failed"] += 1

    # -- pipeline ----------------------------------------------------------

    async def upload_document(
        self, session: AsyncSession, tenant_id: str, filename: str, content: bytes
    ) -> UploadResponse:
        """Validate, store and register an uploaded document."""
        extension = Path(filename).suffix.lower()
        if extension not in self.settings.allowed_extensions:
            raise ValueError(
                f"Unsupported file type '{extension}'. "
                f"Allowed: {sorted(self.settings.allowed_extensions)}"
            )
        if not content:
            raise ValueError("Uploaded file is empty")
        if len(content) > self.settings.max_upload_size_mb * 1024 * 1024:
            raise ValueError(
                f"File exceeds the maximum size of {self.settings.max_upload_size_mb} MB"
            )

        document_id = str(uuid.uuid4())
        target_dir = self.settings.storage_dir / tenant_id / document_id
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename
        file_path.write_bytes(content)

        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            filename=filename,
            document_type=self._document_type(extension),
            status=DocumentStatus.UPLOADED,
            file_path=str(file_path),
            size_bytes=len(content),
        )
        await self.repository.create(session, document)
        logger.info("Document uploaded: id=%s filename=%s tenant=%s", document_id, filename, tenant_id)
        return UploadResponse(document_id=document_id, filename=filename, status=document.status)

    async def process_document(
        self, session: AsyncSession, document_id: str, tenant_id: str
    ) -> ProcessResponse:
        """Parse, validate, chunk, store and structure a previously uploaded document."""
        document = await self._require_document(session, document_id, tenant_id)
        document.status = DocumentStatus.PROCESSING
        document.error = None
        await self.repository.update(session, document)

        started = time.perf_counter()
        failed_marked = False
        try:
            content = Path(document.file_path).read_bytes()
            parsed: ParsedDocument = parse_file(document.filename, content)
            chunks = chunk_document(
                parsed,
                document.id,
                document.filename,
                document.document_type,
                self.settings,
                embedding_provider=self.embedding_provider,
            )
            if not chunks:
                raise ProcessingError(f"No extractable text found in document {document_id}")

            try:
                self.validator.validate(document.filename, content, parsed, chunks)
            except DocumentValidationError as exc:
                await self._mark_failed(session, document, exc, quarantine=True)
                failed_marked = True
                logger.warning("Document validation failed: id=%s error=%s", document_id, exc)
                raise ProcessingError(str(exc)) from exc

            # Idempotency on reprocessing: drop this document's previously
            # derived chunks, structured rules and missing references before
            # re-deriving them.
            await self.document_chunk_repository.delete_by_document(
                session, document.id
            )
            await self.security_rule_repository.delete_by_document(
                session, document.id
            )
            await self.missing_reference_repository.delete_by_document(
                session, document.id
            )

            await self.document_chunk_repository.create_many(
                session, tenant_id, chunks
            )

            rules = self.rule_structurer.structure(
                chunks, tenant_id, document.id
            )
            await self.security_rule_repository.create_many(
                session, tenant_id, rules
            )
            await self._record_missing_references(
                session, tenant_id, document.id, rules
            )
            logger.info(
                "Structured %d rules for tenant=%s document_id=%s",
                len(rules),
                tenant_id,
                document.id,
            )

            document.page_count = len(parsed.pages)
            document.chunk_count = len(chunks)
            document.status = DocumentStatus.PROCESSED
            document.processed_at = datetime.now(timezone.utc)
            await self.repository.update(session, document)

            self._metrics["processed"] += 1
            self._metrics["total_chunks"] += len(chunks)
            logger.info("Document processed: id=%s chunks=%d", document_id, len(chunks))

            return ProcessResponse(
                document_id=document_id,
                status=document.status,
                chunks_created=len(chunks),
                pages_parsed=len(parsed.pages),
            )
        except Exception as exc:
            if not failed_marked:
                await self._mark_failed(session, document, exc)
            logger.exception("Document processing failed: id=%s", document_id)
            if isinstance(exc, DocumentServiceError):
                raise
            raise ProcessingError(f"Processing failed for {document_id}: {exc}") from exc
        finally:
            self._metrics["total_time"] += time.perf_counter() - started

    # -- retrieval ---------------------------------------------------------

    async def get_document(
        self, session: AsyncSession, document_id: str, tenant_id: str
    ) -> Document:
        """Return metadata for a single document."""
        return await self._require_document(session, document_id, tenant_id)

    async def search(
        self,
        query: str,
        tenant_id: str,
        top_k: int | None = 5,
        filename: str | None = None,
        document_type: DocumentType | None = None,
        document_id: str | None = None,
        min_score: float | None = None,
    ) -> SearchResponse:
        """Run full-text similarity search over a tenant's stored chunks.

        Chunks whose ``pg_trgm`` similarity score falls below ``min_score`` (or
        the configured ``settings.min_search_score`` when ``min_score`` is
        ``None``) are dropped. When nothing passes the threshold, an empty result
        set with an explanatory ``message`` is returned.

        When ``top_k`` is ``None``, every matching chunk is considered.
        """
        threshold = min_score if min_score is not None else self.settings.min_search_score
        rows = await self.document_chunk_repository.search(
            session,
            tenant_id,
            query,
            top_k=top_k,
            filename=filename,
            document_type=document_type.value if document_type is not None else None,
            document_id=document_id,
            min_score=threshold,
        )

        results: list[SearchResult] = [
            SearchResult(
                document_id=chunk.document_id,
                text=chunk.text,
                source=chunk.source,
                page=chunk.page,
                score=round(score, 6),
            )
            for chunk, score in rows
        ]

        if not results:
            return SearchResponse(
                query=query,
                results=[],
                message="Релевантных правил не найдено. Уточните запрос.",
            )
        return SearchResponse(query=query, results=results, message="Success")

    async def delete_document(
        self, session: AsyncSession, document_id: str, tenant_id: str
    ) -> DeleteResponse:
        """Delete a document and all of its derived records."""
        document = await self._require_document(session, document_id, tenant_id)

        file_path = Path(document.file_path)
        if file_path.exists():
            file_path.unlink()
        try:  # best-effort cleanup of the now-empty per-document directory
            file_path.parent.rmdir()
        except OSError:
            pass

        await self.repository.delete(session, document_id)
        logger.info("Document deleted: id=%s tenant=%s", document_id, tenant_id)
        return DeleteResponse(document_id=document_id, deleted=True)

    async def list_missing_references(
        self, session: AsyncSession, tenant_id: str
    ) -> list[MissingReference]:
        """Return every missing internal-document reference for a tenant."""
        return await self.missing_reference_repository.list_by_tenant(
            session, tenant_id
        )

    async def clear_missing_references(
        self, session: AsyncSession, tenant_id: str
    ) -> int:
        """Delete every missing reference for a tenant and return the count."""
        return await self.missing_reference_repository.delete_by_tenant(
            session, tenant_id
        )

    async def extract_rules(
        self,
        session: AsyncSession,
        tenant_id: str,
        topic: str | None = None,
        section: str | None = None,
    ) -> list[SecurityRule]:
        """Read structured rules from ``security_rules`` by optional filters."""
        return await self.security_rule_repository.list_by_filters(
            session, tenant_id, topic=topic, section=section
        )

    async def _document_exists(
        self, session: AsyncSession, tenant_id: str, reference: str
    ) -> bool:
        """Return ``True`` when a tenant document matches ``reference`` by filename."""
        statement = select(DocumentORM.id).where(
            DocumentORM.tenant_id == tenant_id,
            DocumentORM.filename == reference,
        )
        result = await session.execute(statement)
        return result.scalar() is not None

    async def _record_missing_references(
        self,
        session: AsyncSession,
        tenant_id: str,
        document_id: str,
        rules: list[SecurityRule],
    ) -> None:
        """Record and log internal documents referenced by rules but not uploaded."""
        for rule in rules:
            for reference in rule.linked_docs:
                if await self._document_exists(session, tenant_id, reference):
                    continue
                await self.missing_reference_repository.create(
                    session, tenant_id, document_id, reference, rule.section
                )
                logger.warning(
                    "Не найден документ, упоминаемый в правиле: %s. "
                    "Загрузите его для полного анализа.",
                    reference,
                )

    def get_metrics(self) -> MetricsResponse:
        """Return aggregated processing metrics."""
        attempts = self._metrics["processed"] + self._metrics["failed"]
        average = self._metrics["total_time"] / attempts if attempts else 0.0
        return MetricsResponse(
            documents_processed=self._metrics["processed"],
            documents_failed=self._metrics["failed"],
            total_chunks=self._metrics["total_chunks"],
            average_processing_seconds=round(average, 4),
        )


_service: DocumentService | None = None


def get_document_service() -> DocumentService:
    """Return a lazily-initialised singleton :class:`DocumentService`."""
    global _service
    if _service is None:
        _service = DocumentService()
    return _service
