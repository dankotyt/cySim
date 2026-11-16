"""Normalisation and content hashing for security rules.

The hash is the rule's stable identity for de-duplication: two rules with the
same topic and the same normalised text are considered the same rule, even if
they came from different documents or extraction runs.
"""
import hashlib
import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_rule_text(text: str) -> str:
    """Collapse whitespace, trim and casefold a rule description."""
    return _WHITESPACE_RE.sub(" ", text or "").strip().casefold()


def rule_content_hash(topic: str, description: str) -> str:
    """Return a stable hash of ``(topic, normalised description)``."""
    payload = f"{topic}\x1f{normalize_rule_text(description)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
