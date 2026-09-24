"""Unit tests for semantic chunking."""
from app.models.document import DocumentType
from app.utils.chunking import chunk_document
from app.utils.parsers import PageText, ParsedDocument


def _parsed(text: str, pages: list[PageText]) -> ParsedDocument:
    return ParsedDocument(text=text, pages=pages)


def test_chunk_document_splits_long_text(settings):
    parsed = _parsed(
        "word " * 5000,
        [PageText(page_number=1, text="word " * 5000)],
    )
    chunks = chunk_document(parsed, "doc-1", "policy.txt", DocumentType.TXT, settings)
    assert len(chunks) > 1


def test_chunk_document_preserves_metadata(settings):
    page_text = "sentence one. " + ("word " * 500)
    parsed = _parsed(page_text, [PageText(page_number=3, text=page_text)])

    chunks = chunk_document(parsed, "doc-1", "policy.txt", DocumentType.TXT, settings)

    assert chunks, "expected at least one chunk"
    for index, chunk in enumerate(chunks):
        assert chunk.document_id == "doc-1"
        assert chunk.source == "policy.txt"
        assert chunk.page == 3
        assert chunk.document_type == DocumentType.TXT
        assert chunk.chunk_index == index
        assert chunk.id


def test_chunk_document_respects_configured_size(settings):
    settings.chunk_size = 50
    settings.chunk_overlap = 0

    text = " ".join(f"token{i}" for i in range(200))
    parsed = _parsed(text, [PageText(page_number=1, text=text)])

    chunks = chunk_document(parsed, "doc-1", "p.txt", DocumentType.TXT, settings)
    assert len(chunks) > 5
    assert all(len(chunk.text) <= 50 for chunk in chunks)


def test_chunk_document_skips_empty_pages(settings):
    parsed = _parsed(
        "actual content",
        [PageText(page_number=1, text=""), PageText(page_number=2, text="actual content")],
    )
    chunks = chunk_document(parsed, "doc-1", "p.txt", DocumentType.TXT, settings)
    assert [chunk.page for chunk in chunks] == [2]
