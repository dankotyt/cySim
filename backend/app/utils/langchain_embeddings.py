"""LangChain ``Embeddings`` adapter over the project's :class:`EmbeddingProvider`.

LangChain's ``SemanticChunker`` consumes a ``langchain_core.embeddings.Embeddings``
object, while the rest of the project speaks the narrower
:class:`~app.utils.embeddings.EmbeddingProvider` interface. This adapter bridges
the two without re-instantiating the (potentially expensive) embedding backend.
"""
from langchain_core.embeddings import Embeddings

from .embeddings import EmbeddingProvider


class LangChainEmbeddingsAdapter(Embeddings):
    """Wrap an existing :class:`EmbeddingProvider` for LangChain consumers."""

    def __init__(self, provider: EmbeddingProvider) -> None:
        self._provider = provider

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents (chunks)."""
        return self._provider.embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self._provider.embed_query(text)
