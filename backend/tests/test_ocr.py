"""Unit tests for the OCR fallback."""
import sys
import types

from app.utils.ocr import OcrExtractor, ocr_pdf_text


def test_ocr_pdf_text_returns_none_for_invalid_input():
    # Without pytesseract/pdf2image (or for non-PDF bytes) this must degrade
    # gracefully to None rather than raising.
    assert ocr_pdf_text(b"not-a-pdf") is None


def test_ocr_extractor_extracts_text(monkeypatch):
    fake_tesseract = types.SimpleNamespace(
        image_to_string=lambda image, lang: "распознанный текст"
    )
    fake_pdf2image = types.SimpleNamespace(
        convert_from_bytes=lambda content: [object()]
    )
    monkeypatch.setitem(sys.modules, "pytesseract", fake_tesseract)
    monkeypatch.setitem(sys.modules, "pdf2image", fake_pdf2image)

    assert OcrExtractor().extract(b"pdf-bytes") == "распознанный текст"
