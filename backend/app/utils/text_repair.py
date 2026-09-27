"""Repair helpers for broken text extracted from Russian PDFs.

PDF text extraction often produces artifacts that are harmless for Latin
scripts but break Cyrillic content: soft hyphens, zero-width characters,
ligatures and, worst of all, UTF-8 bytes re-decoded as Latin-1 (mojibake).

All repairs here are conservative and idempotent: they never remove real
content and never alter already-clean text.
"""
import re

# Characters that should be dropped rather than replaced.
_REMOVE_CHARS = (
    "\u00ad",  # soft hyphen
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\u2060",  # word joiner
    "\ufeff",  # byte order mark / zero width no-break space
)

# Common PDF ligatures mapped back to their ASCII sequences.
_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "ft",
    "\ufb06": "st",
}

# Latin-1 high code points that appear when UTF-8 Cyrillic is decoded as
# Latin-1/cp1252 — a reliable signal of mojibake.
_MOJIBAKE_MARKER_RE = re.compile(r"[\u00c0-\u00ff]")


def _cyrillic_ratio(text: str) -> float:
    """Return the fraction of Cyrillic characters in ``text``."""
    if not text:
        return 0.0
    cyrillic = sum(1 for char in text if "\u0400" <= char <= "\u04ff")
    return cyrillic / len(text)


def _repair_mojibake(text: str) -> str:
    """Reverse Latin-1-decoded UTF-8 when it yields more Cyrillic text.

    Only runs on text that is almost entirely non-Cyrillic: if the input
    already contains Cyrillic, re-encoding the whole string would corrupt the
    correct portion, so it is left untouched.
    """
    if not _MOJIBAKE_MARKER_RE.search(text):
        return text
    if _cyrillic_ratio(text) > 0.05:
        return text

    best = text
    # latin-1 first: it is a lossless round-trip for all 256 byte values,
    # whereas cp1252 has undefined bytes (e.g. 0x8F) and would drop them.
    for encoding in ("latin-1", "cp1252"):
        try:
            candidate = text.encode(encoding, errors="ignore").decode(
                "utf-8", errors="ignore"
            )
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if _cyrillic_ratio(candidate) > _cyrillic_ratio(best):
            best = candidate
    return best


def repair_russian_text(text: str) -> str:
    """Apply conservative repairs for Russian PDF extraction artifacts."""
    text = text.replace("\u00a0", " ")  # non-breaking space -> regular space
    for char in _REMOVE_CHARS:
        text = text.replace(char, "")
    for ligature, replacement in _LIGATURES.items():
        text = text.replace(ligature, replacement)
    return _repair_mojibake(text)
