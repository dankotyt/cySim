"""Unit tests for the multi-level document validator."""
import pytest

from app.services.document_validator import (
    DocumentValidationError,
    DocumentValidator,
    _cosine_similarity,
)
from app.utils.parsers import PageText, ParsedDocument
from tests.fakes import FakeEmbeddingProvider


class _ConstantEmbeddingProvider(FakeEmbeddingProvider):
    """Return the same vector for every input, fully controlling similarity."""

    def __init__(self, vector: list[float]) -> None:
        super().__init__()
        self._vector_value = vector

    def embed_texts(self, texts):
        return [self._vector_value for _ in texts]


def _validator(settings, vector=None):
    provider = _ConstantEmbeddingProvider(vector or [1.0, 0.0])
    return DocumentValidator(settings, provider)


def _parsed(text: str) -> ParsedDocument:
    return ParsedDocument(text=text, pages=[PageText(page_number=1, text=text)])


def test_cosine_similarity_identical_vectors():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_validate_mime_accepts_matching_type(settings):
    validator = _validator(settings)
    validator._detect_mime = lambda content: "application/pdf"
    validator._validate_mime("doc.pdf", b"fake-bytes")


def test_validate_mime_rejects_mismatch(settings):
    validator = _validator(settings)
    validator._detect_mime = lambda content: "application/zip"
    with pytest.raises(DocumentValidationError):
        validator._validate_mime("doc.pdf", b"fake-bytes")


def test_validate_mime_accepts_text_subtype(settings):
    validator = _validator(settings)
    validator._detect_mime = lambda content: "text/x-python"
    validator._validate_mime("note.txt", b"print('hello')")


def test_validate_volume_rejects_short_text(settings):
    validator = _validator(settings)
    settings.min_document_chars = 100
    with pytest.raises(DocumentValidationError):
        validator._validate_volume(_parsed("short"), [object()])


def test_validate_volume_rejects_few_chunks(settings):
    validator = _validator(settings)
    settings.min_document_chars = 1
    settings.min_document_chunks = 2
    with pytest.raises(DocumentValidationError):
        validator._validate_volume(_parsed("long enough"), [object()])


def test_validate_relevance_passes_above_threshold(settings):
    validator = _validator(settings, vector=[1.0, 0.0])
    validator._reference_vectors = lambda: [[1.0, 0.0]]
    settings.relevance_threshold = 0.5
    validator._validate_relevance("security rules")


def test_validate_relevance_fails_below_threshold(settings):
    validator = _validator(settings, vector=[1.0, 0.0])
    validator._reference_vectors = lambda: [[0.0, 1.0]]
    settings.relevance_threshold = 0.5
    with pytest.raises(DocumentValidationError):
        validator._validate_relevance("unrelated topic")
