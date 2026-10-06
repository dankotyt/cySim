"""Multi-level validation for uploaded security documents.

Validation runs during document processing and applies two levels:

1. **MIME** — the detected content type (via ``python-magic``) must match the
   declared file extension (PDF, DOCX or TXT).
2. **Volume** — the parsed text and the resulting chunk count must meet the
   configured minimums.

A failed level raises :class:`DocumentValidationError` (a subclass of
``ValueError``) so callers can move the file to quarantine and mark the
document as ``FAILED``.
"""
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..core.logging import get_logger
from ..utils.parsers import ParsedDocument

logger = get_logger(__name__)


class DocumentValidationError(ValueError):
    """Raised when a document fails a validation level."""


_EXPECTED_MIME: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        # libmagic on some platforms reports DOCX as a generic ZIP container.
        "application/zip",
    },
    ".txt": set(),
}

# MIME types that are acceptable for plain-text uploads regardless of subtype.
_TEXT_MIME_PREFIXES = ("text/",)
_GENERIC_MIME = {"application/octet-stream", "inode/x-empty"}


class DocumentValidator:
    """Validate uploaded documents against the configured policy."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _detect_mime(self, content: bytes) -> str:
        """Return the detected MIME type for ``content``."""
        import magic  # local import; requires libmagic on the host

        return magic.from_buffer(content, mime=True)

    def _validate_mime(self, filename: str, content: bytes) -> None:
        """Ensure the detected MIME type matches the file extension."""
        extension = Path(filename).suffix.lower()
        if extension not in _EXPECTED_MIME:
            raise DocumentValidationError(
                f"Unsupported file type '{extension}' for validation"
            )

        detected = self._detect_mime(content)
        if extension == ".txt":
            if detected.startswith(_TEXT_MIME_PREFIXES) or detected in _GENERIC_MIME:
                return
            raise DocumentValidationError(
                f"Detected MIME type '{detected}' is not plain text"
            )

        if detected in _EXPECTED_MIME[extension]:
            return
        raise DocumentValidationError(
            f"Detected MIME type '{detected}' does not match extension '{extension}'"
        )

    def _validate_volume(self, parsed: ParsedDocument, chunks: list[Any]) -> None:
        """Ensure the document has enough characters and chunks."""
        if len(parsed.text) < self.settings.min_document_chars:
            raise DocumentValidationError(
                f"Document text is too short: {len(parsed.text)} characters "
                f"(minimum {self.settings.min_document_chars})"
            )
        if len(chunks) < self.settings.min_document_chunks:
            raise DocumentValidationError(
                f"Document produced {len(chunks)} chunks "
                f"(minimum {self.settings.min_document_chunks})"
            )

    def validate(
        self,
        filename: str,
        content: bytes,
        parsed: ParsedDocument,
        chunks: list[Any],
    ) -> None:
        """Run all validation levels, raising on the first failure."""
        self._validate_mime(filename, content)
        self._validate_volume(parsed, chunks)
