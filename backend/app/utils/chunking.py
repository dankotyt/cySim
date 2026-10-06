"""Recursive text splitting of parsed documents.

Documents are split with LangChain's ``RecursiveCharacterTextSplitter``,
preserving the page boundary of each chunk so downstream consumers can attach
accurate provenance metadata.
"""
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..core.config import Settings
from ..core.logging import get_logger
from ..models.document import Chunk, DocumentType
from .parsers import ParsedDocument

logger = get_logger(__name__)


def _build_recursive_chunker(settings: Settings) -> RecursiveCharacterTextSplitter:
    """Build the recursive splitter used for every document."""
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
) -> list[Chunk]:
    """Split a parsed document into chunks, preserving page metadata."""
    splitter = _build_recursive_chunker(settings)
    logger.info(
        "Using RecursiveCharacterTextSplitter (chunk_size=%d, overlap=%d)",
        settings.chunk_size,
        settings.chunk_overlap,
    )

    chunks: list[Chunk] = []
    for page in parsed.pages:
        if not page.text:
            continue
        chunks.extend(
            _make_chunks(
                splitter.split_text(page.text),
                page.page_number,
                document_id,
                source,
                document_type,
            )
        )
    return chunks
