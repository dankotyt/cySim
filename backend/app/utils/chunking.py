"""Semantic chunking of parsed documents."""
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..core.config import Settings
from ..models.document import Chunk, DocumentType
from .parsers import ParsedDocument


def chunk_document(
    parsed: ParsedDocument,
    document_id: str,
    source: str,
    document_type: DocumentType,
    settings: Settings,
) -> list[Chunk]:
    """Split a parsed document into overlapping chunks, preserving page metadata.

    Chunking happens per page so that each chunk carries an accurate page number.
    ``chunk_index`` records the chunk position within its page.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[Chunk] = []
    for page in parsed.pages:
        if not page.text:
            continue
        for index, text in enumerate(splitter.split_text(page.text)):
            chunks.append(
                Chunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    text=text,
                    page=page.page_number,
                    chunk_index=index,
                    source=source,
                    document_type=document_type,
                )
            )
    return chunks
