"""Shared test doubles."""
import hashlib

from app.services.document_validator import DocumentValidationError
from app.utils.embeddings import EmbeddingProvider


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic, dependency-free embedding provider for tests."""

    name = "fake"

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        ints = [int.from_bytes(digest[i : i + 4], "big") for i in range(0, 32, 4)]
        norm = (sum(value * value for value in ints) ** 0.5) or 1.0
        normalized = [value / norm for value in ints]
        return (normalized + [0.0] * self.dim)[: self.dim]

    def embed_texts(self, texts):
        return [self._vector(text) for text in texts]


class FakeValidator:
    """No-op validator that bypasses MIME/libmagic checks in API tests."""

    def validate(self, filename: str, content: bytes, parsed, chunks) -> None:
        return None


class FailingValidator:
    """Validator that always fails, to exercise the quarantine/FAILED path."""

    def validate(self, filename: str, content: bytes, parsed, chunks) -> None:
        raise DocumentValidationError("simulated validation failure")
