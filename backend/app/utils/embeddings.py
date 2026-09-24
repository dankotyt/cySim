"""Embedding generation via Ollama (bge-m3) with sentence-transformers fallback."""
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence

from ..core.config import Settings
from ..core.logging import get_logger

logger = get_logger(__name__)


def embed_in_batches(
    texts: list[str],
    batch_size: int,
    embed_fn: Callable[[list[str]], list[list[float]]],
) -> list[list[float]]:
    """Split ``texts`` into batches and concatenate the resulting embeddings."""
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        embeddings.extend(embed_fn(texts[start : start + batch_size]))
    return embeddings


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding backends."""

    name: str = "base"

    @abstractmethod
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a sequence of texts and return one vector per text."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self.embed_texts([text])[0]


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embedding backend backed by a local Ollama instance running ``bge-m3``."""

    name = "ollama"

    def __init__(self, model: str, base_url: str, batch_size: int = 32) -> None:
        import ollama  # local import to keep the fallback path optional

        self.model = model
        self.batch_size = batch_size
        self._client = ollama.Client(host=base_url)

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        response = self._client.embed(model=self.model, input=batch)
        return response["embeddings"]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return embed_in_batches(list(texts), self.batch_size, self._embed_batch)

    def is_available(self) -> bool:
        """Return ``True`` when the Ollama endpoint responds to an embed request."""
        try:
            self._embed_batch(["ping"])
            return True
        except Exception as exc:  # noqa: BLE001 - availability check must not raise
            logger.warning("Ollama embedding backend unavailable: %s", exc)
            return False


class SentenceTransformerProvider(EmbeddingProvider):
    """Local embedding backend backed by ``sentence-transformers``."""

    name = "sentence-transformers"

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer  # local import (heavy)

        self.model = SentenceTransformer(model_name)
        self.batch_size = batch_size

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        vectors = self.model.encode(batch, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return embed_in_batches(list(texts), self.batch_size, self._embed_batch)


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Return the configured provider, falling back when Ollama is unavailable."""
    if settings.embedding_provider.lower() == "ollama":
        provider = OllamaEmbeddingProvider(
            model=settings.embedding_model,
            base_url=settings.ollama_base_url,
            batch_size=settings.embedding_batch_size,
        )
        if provider.is_available():
            logger.info("Using Ollama embedding provider (model=%s)", settings.embedding_model)
            return provider
        logger.warning(
            "Ollama unavailable; falling back to sentence-transformers (model=%s)",
            settings.sentence_transformer_model,
        )

    try:
        provider = SentenceTransformerProvider(
            model_name=settings.sentence_transformer_model,
            batch_size=settings.embedding_batch_size,
        )
        logger.info(
            "Using sentence-transformers embedding provider (model=%s)",
            settings.sentence_transformer_model,
        )
        return provider
    except ImportError as exc:
        raise RuntimeError(
            "No embedding backend is available: Ollama is offline and "
            "sentence-transformers is not installed. Start Ollama or run "
            "`pip install sentence-transformers`."
        ) from exc
