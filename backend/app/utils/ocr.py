"""OCR fallback for scanned (image-only) PDF documents.

``pypdf`` can only extract embedded text; scanned PDFs contain images and
yield no text. This module provides a graceful OCR fallback backed by
Tesseract. The heavy dependencies are imported lazily so the module stays
optional: if ``pytesseract`` / ``pdf2image`` (or the ``tesseract`` binary and
``poppler``) are not installed, :func:`ocr_pdf_text` returns ``None`` and the
caller falls back to the normal (empty) extraction path.

Install (optional):

    pip install pytesseract pdf2image
    # plus system packages: tesseract-ocr, tesseract-ocr-rus, poppler-utils
"""
from ..core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_OCR_LANGUAGE = "rus+eng"


class OcrExtractor:
    """Extract text from an image-based PDF using Tesseract."""

    def __init__(self, language: str = DEFAULT_OCR_LANGUAGE) -> None:
        self.language = language

    def extract(self, content: bytes) -> str:
        """Return OCR text for ``content`` (a PDF byte string)."""
        import pytesseract  # local import: optional dependency
        from pdf2image import convert_from_bytes  # local import: optional dependency

        images = convert_from_bytes(content)
        return "\n\n".join(
            pytesseract.image_to_string(image, lang=self.language)
            for image in images
        )


def ocr_pdf_text(
    content: bytes, language: str = DEFAULT_OCR_LANGUAGE
) -> str | None:
    """Return OCR text for a scanned PDF, or ``None`` if OCR is unavailable.

    Never raises: missing dependencies or a failed conversion degrade to
    ``None`` so the caller can fall back gracefully.
    """
    try:
        return OcrExtractor(language=language).extract(content)
    except Exception as exc:  # noqa: BLE001 - graceful degradation required
        logger.warning("OCR fallback unavailable: %s", exc)
        return None
