"""Multi-level validation for uploaded security documents.

Validation runs during document processing and applies three levels:

1. **MIME** — the detected content type (via ``python-magic``) must match the
   declared file extension (PDF, DOCX or TXT).
2. **Volume** — the parsed text and the resulting chunk count must meet the
   configured minimums.
3. **Relevance** — the document embedding must be sufficiently similar (cosine)
   to a fixed set of information-security reference phrases.

A failed level raises :class:`DocumentValidationError` (a subclass of
``ValueError``) so callers can move the file to quarantine and mark the
document as ``FAILED``.
"""
import math
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..core.logging import get_logger
from ..utils.embeddings import EmbeddingProvider
from ..utils.parsers import ParsedDocument

logger = get_logger(__name__)


class DocumentValidationError(ValueError):
    """Raised when a document fails a validation level."""


_REFERENCE_PHRASES: tuple[str, ...] = (
    "правила информационной безопасности",
    "запрещено передавать пароли и учётные данные",
    "конфиденциальные данные и персональные данные",
    "политика аутентификации и управления доступом",
    "фишинг и социальная инженерия",
    "физическая безопасность и пропускной режим",
    "удалённая работа и VPN",
    "утечка данных и инсайдерские угрозы",
)

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

_RELEVANCE_SAMPLE_CHARS = 4000


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of two vectors (0.0 when degenerate)."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class DocumentValidator:
    """Validate uploaded documents against the configured policy."""

    def __init__(self, settings: Settings, embedding_provider: EmbeddingProvider) -> None:
        self.settings = settings
        self.embedding_provider = embedding_provider
        self._reference_vectors_cache: list[list[float]] | None = None

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

    def _reference_vectors(self) -> list[list[float]]:
        """Return (lazily cached) embeddings for the reference phrases."""
        if self._reference_vectors_cache is None:
            self._reference_vectors_cache = [
                self.embedding_provider.embed_query(phrase)
                for phrase in _REFERENCE_PHRASES
            ]
        return self._reference_vectors_cache

    def _validate_relevance(self, text: str) -> None:
        """Ensure the document is topically relevant to information security."""
        sample = text[:_RELEVANCE_SAMPLE_CHARS]
        document_vector = self.embedding_provider.embed_query(sample)
        best = max(
            _cosine_similarity(document_vector, reference)
            for reference in self._reference_vectors()
        )
        if best < self.settings.relevance_threshold:
            raise DocumentValidationError(
                f"Relevance score {best:.3f} is below threshold "
                f"{self.settings.relevance_threshold}"
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
        self._validate_relevance(parsed.text)
