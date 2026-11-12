"""Unit tests for document validation (MIME + volume)."""
import pytest

from app.services.document_validator import (
    DocumentValidationError,
    DocumentValidator,
)
from app.utils.parsers import PageText, ParsedDocument


def _validator(settings) -> DocumentValidator:
    return DocumentValidator(settings)


def _parsed(text: str) -> ParsedDocument:
    return ParsedDocument(text=text, pages=[PageText(page_number=1, text=text)])


def test_validate_mime_accepts_matching_type(settings):
    validator = _validator(settings)
    validator._detect_mime = lambda content: "application/pdf"
    validator._validate_mime("doc.pdf", b"fake-bytes")


def test_validate_mime_accepts_docx_as_zip_container(settings):
    validator = _validator(settings)
    validator._detect_mime = lambda content: "application/zip"
    validator._validate_mime("doc.docx", b"fake-bytes")


def test_validate_mime_rejects_mismatch(settings):
    validator = _validator(settings)
    validator._detect_mime = lambda content: "application/zip"
    with pytest.raises(DocumentValidationError):
        validator._validate_mime("doc.pdf", b"fake-bytes")


def test_validate_mime_accepts_text_subtype(settings):
    validator = _validator(settings)
    validator._detect_mime = lambda content: "text/x-python"
    validator._validate_mime("note.txt", b"print('hello')")


def test_validate_mime_rejects_binary_for_txt(settings):
    validator = _validator(settings)
    validator._detect_mime = lambda content: "application/pdf"
    with pytest.raises(DocumentValidationError):
        validator._validate_mime("note.txt", b"%PDF-1.7")


def test_validate_mime_rejects_unknown_extension(settings):
    validator = _validator(settings)
    with pytest.raises(DocumentValidationError):
        validator._validate_mime("archive.zip", b"data")


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


def test_validate_volume_accepts_sufficient_document(settings):
    validator = _validator(settings)
    settings.min_document_chars = 1
    settings.min_document_chunks = 1
    validator._validate_volume(_parsed("long enough"), [object()])


def test_validate_runs_mime_before_volume(settings):
    validator = _validator(settings)
    calls: list[str] = []
    validator._validate_mime = lambda *args: calls.append("mime")
    validator._validate_volume = lambda *args: calls.append("volume")

    validator.validate("doc.pdf", b"fake-bytes", _parsed("text"), [object()])

    assert calls == ["mime", "volume"]
