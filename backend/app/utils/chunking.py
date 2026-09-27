"""Semantic chunking of parsed documents.

Primary splitter is LangChain's ``SemanticChunker`` (splits at points where the
embedding similarity between consecutive sentences drops below a percentile
breakpoint). When semantic chunking is disabled or fails, the module falls back
to ``RecursiveCharacterTextSplitter``.
"""
import uuid
from typing import TYPE_CHECKING

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..core.config import Settings
from ..core.logging import get_logger
from ..models.document import Chunk, DocumentType
from .embeddings import EmbeddingProvider
from .langchain_embeddings import LangChainEmbeddingsAdapter
from .parsers import ParsedDocument

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from langchain_experimental.text_splitter import SemanticChunker

logger = get_logger(__name__)


def _build_semantic_chunker(
    settings: Settings, embedding_provider: EmbeddingProvider
) -> "SemanticChunker":
    """Build a :class:`SemanticChunker` backed by the existing provider."""
    from langchain_experimental.text_splitter import SemanticChunker

    return SemanticChunker(
        embeddings=LangChainEmbeddingsAdapter(embedding_provider),
        breakpoint_threshold_type=settings.semantic_breakpoint_type,
        breakpoint_threshold_amount=settings.semantic_breakpoint_amount,
        add_start_index=True,
    )


def _build_recursive_chunker(settings: Settings) -> RecursiveCharacterTextSplitter:
    """Build the legacy recursive splitter used as a fallback."""
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _make_chunks(
    texts: list[str],
    page_number: int,
    document_id: str,
    source: str,
    document_type: DocumentType,
) -> list[Chunk]:
    """Wrap split text fragments into :class:`Chunk` records."""
    return [
        Chunk(
            id=str(uuid.uuid4()),
            document_id=document_id,
            text=text,
            page=page_number,
            chunk_index=index,
            source=source,
            document_type=document_type,
        )
        for index, text in enumerate(texts)
    ]


def chunk_document(
    parsed: ParsedDocument,
    document_id: str,
    source: str,
    document_type: DocumentType,
    settings: Settings,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[Chunk]:
    """Split a parsed document into chunks, preserving page metadata.

    When ``semantic_chunking_enabled`` is set and an ``embedding_provider`` is
    supplied, the document is split with LangChain's ``SemanticChunker``
    (per page, so each chunk keeps an accurate page number). On any failure the
    function falls back to ``RecursiveCharacterTextSplitter``.

    The ``embedding_provider`` should be the singleton owned by
    :class:`~app.services.document_service.DocumentService` so that the backend
    is not re-instantiated per document.
    """
    semantic_chunker = None
    recursive_chunker: RecursiveCharacterTextSplitter | None = None

    if settings.semantic_chunking_enabled and embedding_provider is not None:
        try:
            semantic_chunker = _build_semantic_chunker(settings, embedding_provider)
            logger.info(
                "Using SemanticChunker (breakpoint_type=%s, amount=%s)",
                settings.semantic_breakpoint_type,
                settings.semantic_breakpoint_amount,
            )
        except Exception as exc:  # noqa: BLE001 - must degrade to fallback
            logger.warning(
                "SemanticChunker unavailable (%s); falling back to "
                "RecursiveCharacterTextSplitter (chunk_size=%d, overlap=%d)",
                exc,
                settings.chunk_size,
                settings.chunk_overlap,
            )
            semantic_chunker = None

    if semantic_chunker is None:
        recursive_chunker = _build_recursive_chunker(settings)
        logger.info(
            "Using RecursiveCharacterTextSplitter (chunk_size=%d, overlap=%d)",
            settings.chunk_size,
            settings.chunk_overlap,
        )

    chunks: list[Chunk] = []
    for page in parsed.pages:
        if not page.text:
            continue

        if semantic_chunker is not None:
            try:
                texts = semantic_chunker.split_text(page.text)
            except Exception as exc:  # noqa: BLE001 - per-page fallback
                logger.warning(
                    "SemanticChunker failed on page %d (%s); using recursive splitter",
                    page.page_number,
                    exc,
                )
                if recursive_chunker is None:
                    recursive_chunker = _build_recursive_chunker(settings)
                texts = recursive_chunker.split_text(page.text)
        else:
            texts = recursive_chunker.split_text(page.text)

        chunks.extend(
            _make_chunks(
                texts,
                page.page_number,
                document_id,
                source,
                document_type,
            )
        )

    return chunks
