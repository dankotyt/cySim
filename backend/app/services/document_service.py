"""RAG business logic: ingestion, chunking, embedding, storage and retrieval."""
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..models.document import (
    DeleteResponse,
    Document,
    DocumentStatus,
    DocumentType,
    MetricsResponse,
    ProcessResponse,
    SearchResponse,
    SearchResult,
    SecurityRule,
    UploadResponse,
)
from ..repositories.document_repository import DocumentRepository
from ..utils.chunking import chunk_document
from ..utils.embeddings import EmbeddingProvider, get_embedding_provider
from ..utils.parsers import ParsedDocument, parse_file
from .document_validator import DocumentValidationError, DocumentValidator

logger = get_logger(__name__)

# Будет заменено на вызов LLM
_DEFAULT_RULES_QUERY = (
    "security rules requirements prohibitions policy obligations"
    "правила информационной безопасности запреты требования политика "
    "пароли аутентификация фишинг вишинг социальная инженерия "
    "конфиденциальные данные персональные данные удаленная работа vpn "
    "физическая безопасность пропуск инсайдер утечка "
    "подрядчики цепочка поставок usb носитель"
)

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    # Классические категории ИБ
    "passwords": (
        "password", "пароль", "credential", "authentication", "mfa", "2fa",
        "смена пароля", "сложность пароля",
    ),
    "phishing": (
        "phishing", "фишинг", "attachment", "вложение", "suspicious link",
        "подозрительн", "письмо от", "перейти по ссылке",
    ),
    "physical_security": (
        "badge", "пропуск", "physical access", "физическ", "clean desk",
        "чистый стол", "замок", "сейф",
    ),
    "data_handling": (
        "confidential", "конфиденциальн", "classification", "классификац",
        "personal data", "персональн", "коммерческая тайна", "гостайна",
    ),
    "remote_work": (
        "remote", "удаленн", "vpn", "telework", "домашн", "вне офиса",
    ),

    # Социальная инженерия
    "vishing": (
        "звонок", "позвоните", "служба безопасности", "подтвердите код",
        "код из sms", "назовите код", "служба поддержки", "звонил",
        "входящий звонок", "телефонный",
    ),
    "pretexting": (
        "уволен", "увольнение", "новый сотрудник", "отдел кадров",
        "приказ", "сокращение", "перевод на другую должность",
        "кадровый", "hr-отдел", "первый рабочий день",
    ),
    "baiting": (
        "флешка", "usb", "найден", "бонус", "зарплата", "премия",
        "бесплатн", "подарок", "акция", "скачать файл", "загрузка",
    ),
    "tailgating": (
        "пропуск", "дверь", "руки заняты", "забыл карту", "придержать дверь",
        "прошел за спиной", "посторонний", "незнакомый человек",
    ),
    "quid_pro_quo": (
        "помощь", "техподдержка", "взамен", "бесплатно", "обновление",
        "ускорю", "починю", "настрою", "предлагаю услугу",
    ),
    "social_media_osint": (
        "linkedin", "должность", "проект", "конференция", "соцсет",
        "социальные сети", "профиль", "публикац", "подписчик",
    ),
    "shoulder_surfing": (
        "подсмотрел", "экран", "кафе", "самолет", "общественное место",
        "взгляд через плечо", "рядом стоял", "метро", "аэропорт",
    ),
    "dumpster_diving": (
        "мусор", "мусорн", "выброшенные", "документы в мусор",
        "бумаги", "черновик", "корзина для бумаг",
    ),

    # Современные векторы атак
    "supply_chain": (
        "подрядчик", "поставщик", "партнер", "аутсорс", "третий контур",
        "интеграция", "внешний сервис", "вендор", "контрагент",
    ),
    "leaked_credentials": (
        "утечка", "слив баз", "старый пароль", "компрометация",
        "haveibeenpwned", "темная сеть", "dark web", "утекш",
    ),
    "insider_threat": (
        "инсайдер", "бывший сотрудник", "уволенный сотрудник",
        "подрядчик с доступом", "злоупотребление доступом",
    ),
    "usb_drop": (
        "usb-носитель", "разбросан", "парковка", "флешка в туалете",
        "подброшенная флешка", "неизвестный носитель",
    ),
}


class DocumentServiceError(Exception):
    """Base exception for document-service failures."""


class DocumentNotFoundError(DocumentServiceError):
    """Raised when a document id is unknown or belongs to another tenant."""


class ProcessingError(DocumentServiceError):
    """Raised when a document fails to parse, chunk, validate or embed."""


class DocumentService:
    """Facade exposing the full document analysis pipeline.

    The service is the integration point for other modules (e.g. scenario
    generation): it owns ingestion, chunking, embedding, vector storage,
    retrieval and rule extraction.

    Database access is asynchronous; each method receives an
    :class:`AsyncSession` (injected by FastAPI through ``Depends(get_db)``).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        chroma_client: ClientAPI | None = None,
        validator: DocumentValidator | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

        self.repository = DocumentRepository()
        self.embedding_provider = embedding_provider or get_embedding_provider(self.settings)
        self.validator = validator or DocumentValidator(self.settings, self.embedding_provider)
        self._client = chroma_client or self._build_chroma_client()

        self._metrics = {
            "processed": 0,
            "failed": 0,
            "total_chunks": 0,
            "total_time": 0.0,
        }

    # -- helpers -----------------------------------------------------------

    def _build_chroma_client(self) -> ClientAPI:
        """Return a Chroma client, preferring a remote server when configured."""
        if self.settings.use_chroma_server:
            logger.info(
                "Using Chroma server at %s:%d",
                self.settings.chroma_host,
                self.settings.chroma_port,
            )
            return chromadb.HttpClient(
                host=self.settings.chroma_host,
                port=self.settings.chroma_port,
            )
        return chromadb.PersistentClient(path=str(self.settings.chroma_persist_dir))

    def _collection(self, tenant_id: str) -> Any:
        name = self._collection_name(tenant_id)
        return self._client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )

    def _collection_name(self, tenant_id: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "_", tenant_id).strip("_") or "default"
        name = f"{self.settings.collection_prefix}_{sanitized}"
        return name[:63].strip("_-") or "collection"

    @staticmethod
    def _document_type(extension: str) -> DocumentType:
        mapping = {
            ".pdf": DocumentType.PDF,
            ".docx": DocumentType.DOCX,
            ".txt": DocumentType.TXT,
        }
        return mapping[extension]

    @staticmethod
    def _chunk_metadata(chunk: Any) -> dict[str, Any]:
        return {
            "document_id": chunk.document_id,
            "source": chunk.source,
            "page": chunk.page,
            "chunk_index": chunk.chunk_index,
            "document_type": chunk.document_type.value,
        }

    async def _require_document(
        self, session: AsyncSession, document_id: str, tenant_id: str
    ) -> Document:
        document = await self.repository.get(session, document_id)
        if document is None or document.tenant_id != tenant_id:
            raise DocumentNotFoundError(f"Document not found: {document_id}")
        return document

    @staticmethod
    def _build_filter(
        filename: str | None, document_type: DocumentType | None
    ) -> dict[str, str] | None:
        conditions: dict[str, str] = {}
        if filename:
            conditions["source"] = filename
        if document_type:
            conditions["document_type"] = document_type.value
        return conditions or None

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
        """Parse, validate, chunk, embed and store a previously uploaded document."""
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

            embeddings = self.embedding_provider.embed_texts([chunk.text for chunk in chunks])
            collection = self._collection(tenant_id)
            collection.add(
                ids=[chunk.id for chunk in chunks],
                embeddings=embeddings,
                documents=[chunk.text for chunk in chunks],
                metadatas=[self._chunk_metadata(chunk) for chunk in chunks],
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
        top_k: int = 5,
        filename: str | None = None,
        document_type: DocumentType | None = None,
        min_score: float | None = None,
    ) -> SearchResponse:
        """Run semantic search over a tenant's vector store.

        Chunks whose cosine similarity score falls below ``min_score`` (or the
        configured ``settings.min_search_score`` when ``min_score`` is ``None``)
        are dropped. When nothing passes the threshold, an empty result set with
        an explanatory ``message`` is returned.
        """
        collection = self._collection(tenant_id)
        query_embedding = self.embedding_provider.embed_query(query)
        where = self._build_filter(filename, document_type)

        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        ids = response.get("ids", [[]])[0]
        documents = response.get("documents", [[]])[0]
        metadatas = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]

        threshold = min_score if min_score is not None else self.settings.min_search_score

        results: list[SearchResult] = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] or {}
            distance = float(distances[index]) if index < len(distances) else 0.0
            score = round(1.0 - distance, 6)
            if score < threshold:
                continue
            results.append(
                SearchResult(
                    document_id=metadata.get("document_id", chunk_id),
                    text=documents[index] if index < len(documents) else "",
                    source=metadata.get("source", ""),
                    page=metadata.get("page", 1),
                    score=score,
                )
            )

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
        """Delete a document and all of its embeddings."""
        document = await self._require_document(session, document_id, tenant_id)
        self._collection(tenant_id).delete(where={"document_id": document_id})

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

    async def extract_rules(
        self,
        tenant_id: str,
        query: str | None = None,
        top_k: int = 10,
        filename: str | None = None,
    ) -> list[SecurityRule]:
        """Retrieve rule-relevant chunks and return them as structured rules.

        This is the primary integration point for the scenario generation module.
        """
        response = await self.search(
            query or _DEFAULT_RULES_QUERY,
            tenant_id,
            top_k=top_k,
            filename=filename,
        )
        if not response.results:
            logger.warning(
                "No relevant rules found for tenant=%s query=%s",
                tenant_id,
                query or _DEFAULT_RULES_QUERY,
            )
            return []
        return [
            SecurityRule(
                title=_derive_title(result.text),
                description=result.text,
                category=_classify_category(result.text),
                source=result.source,
                page=result.page,
                score=result.score,
            )
            for result in response.results
        ]

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


def _derive_title(text: str) -> str:
    line = next((line.strip() for line in text.splitlines() if line.strip()), "Rule")
    return line[:80]


def _classify_category(text: str) -> str:
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "general"


_service: DocumentService | None = None


def get_document_service() -> DocumentService:
    """Return a lazily-initialised singleton :class:`DocumentService`."""
    global _service
    if _service is None:
        _service = DocumentService()
    return _service
