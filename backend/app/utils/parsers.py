"""Document parsers for PDF, DOCX and TXT files."""
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from pypdf import PdfReader

from ..core.logging import get_logger
from .ocr import ocr_pdf_text
from .text_repair import repair_russian_text

logger = get_logger(__name__)

# Non-printable/control characters except tab and newline.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTISPACE_RE = re.compile(r"[ \t]+")
_MULTILINE_RE = re.compile(r"\n{3,}")
_MEANINGFUL_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]")


@dataclass
class PageText:
    """Text extracted from a single page."""

    page_number: int
    text: str


@dataclass
class ParsedDocument:
    """Result of parsing a document into plain text."""

    text: str
    pages: list[PageText]
    metadata: dict[str, Any] = field(default_factory=dict)


def clean_text(text: str) -> str:
    """Normalize whitespace and strip common extraction artifacts."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHAR_RE.sub("", text)
    text = _MULTISPACE_RE.sub(" ", text)
    text = _MULTILINE_RE.sub("\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _drop_garbage_lines(text)
    text = repair_russian_text(text)
    return text.strip()

def _drop_garbage_lines(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def parse_txt(content: bytes) -> ParsedDocument:
    """Parse a plain-text file, decoding UTF-8 with replacement."""
    text = clean_text(content.decode("utf-8", errors="replace"))
    return ParsedDocument(text=text, pages=[PageText(page_number=1, text=text)])


def parse_docx(content: bytes) -> ParsedDocument:
    """Parse a DOCX file, including table cell text."""
    doc = DocxDocument(io.BytesIO(content))

    parts = [paragraph.text for paragraph in doc.paragraphs]

    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))

    text = clean_text("\n".join(parts))
    return ParsedDocument(text=text, pages=[PageText(page_number=1, text=text)])


def parse_pdf(content: bytes) -> ParsedDocument:
    """Parse a PDF file page by page, preserving page boundaries.

    Corrupt PDFs degrade gracefully: a failed ``PdfReader`` construction or a
    failed page extraction falls back to OCR; if OCR also yields nothing, an
    empty :class:`ParsedDocument` is returned.
    """
    pages: list[PageText] = []
    try:
        reader = PdfReader(io.BytesIO(content))
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                extracted = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - one bad page must not abort
                logger.warning(
                    "Failed to extract text from page %d: %s", page_number, exc
                )
                continue
            cleaned = clean_text(extracted)
            if cleaned:
                pages.append(PageText(page_number=page_number, text=cleaned))
    except Exception as exc:  # noqa: BLE001 - corrupt PDF falls back to OCR
        logger.warning("Failed to parse PDF: %s", exc)

    if not pages:  # scanned or corrupt PDF: fall back to OCR
        ocr_text = ocr_pdf_text(content)
        if ocr_text:
            cleaned_ocr = clean_text(ocr_text)
            if cleaned_ocr:
                pages = [PageText(page_number=1, text=cleaned_ocr)]

    full_text = "\n\n".join(page.text for page in pages)
    return ParsedDocument(
        text=full_text,
        pages=pages,
        metadata={"page_count": len(pages)},
    )


def parse_file(filename: str, content: bytes) -> ParsedDocument:
    """Dispatch to the correct parser based on the file extension."""
    extension = Path(filename).suffix.lower()

    if extension == ".pdf":
        return parse_pdf(content)
    if extension == ".docx":
        return parse_docx(content)
    if extension == ".txt":
        return parse_txt(content)

    raise ValueError(f"Unsupported file type: {extension}")