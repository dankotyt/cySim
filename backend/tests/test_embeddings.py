"""Unit tests for embedding providers and batching."""
from app.utils import embeddings as embeddings_module
from app.utils.embeddings import (
    OllamaEmbeddingProvider,
    embed_in_batches,
    get_embedding_provider,
)
from tests.fakes import FakeEmbeddingProvider


def test_embed_in_batches_splits_correctly():
    def embed_fn(batch):
        return [[len(text)] for text in batch]

    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    result = embed_in_batches(texts, 2, embed_fn)
    assert result == [[1], [2], [3], [4], [5]]


def test_fake_embedding_provider_is_deterministic():
    provider = FakeEmbeddingProvider()
    first = provider.embed_texts(["same text"])
    second = provider.embed_texts(["same text"])
    assert first == second
    assert provider.embed_query("same text") == first[0]


def test_ollama_provider_batches_requests():
    provider = OllamaEmbeddingProvider.__new__(OllamaEmbeddingProvider)
    provider.model = "bge-m3"
    provider.batch_size = 3

    calls: list[list[str]] = []

    class FakeClient:
        def embed(self, model, input):
            calls.append(list(input))
            return {"embeddings": [[0.1] * 4 for _ in input]}

    provider._client = FakeClient()

    texts = ["a", "b", "c", "d", "e"]
    embeddings = provider.embed_texts(texts)

    assert len(embeddings) == 5
    assert calls == [["a", "b", "c"], ["d", "e"]]


def test_get_embedding_provider_prefers_ollama(monkeypatch, settings):
    class FakeOllama(FakeEmbeddingProvider):
        def __init__(self, model, base_url, batch_size=32):
            super().__init__()

        def is_available(self):
            return True

    monkeypatch.setattr(embeddings_module, "OllamaEmbeddingProvider", FakeOllama)
    provider = get_embedding_provider(settings)
    assert isinstance(provider, FakeOllama)


def test_get_embedding_provider_falls_back_when_ollama_offline(monkeypatch, settings):
    sentinel = FakeEmbeddingProvider()

    monkeypatch.setattr(
        embeddings_module.OllamaEmbeddingProvider, "is_available", lambda self: False
    )
    monkeypatch.setattr(
        embeddings_module, "SentenceTransformerProvider", lambda **kwargs: sentinel
    )

    provider = get_embedding_provider(settings)
    assert provider is sentinel


def test_get_embedding_provider_raises_when_no_backend(monkeypatch, settings):
    monkeypatch.setattr(
        embeddings_module.OllamaEmbeddingProvider, "is_available", lambda self: False
    )

    def raise_import_error(**kwargs):
        raise ImportError("no module")

    monkeypatch.setattr(embeddings_module, "SentenceTransformerProvider", raise_import_error)

    import pytest

    with pytest.raises(RuntimeError, match="No embedding backend"):
        get_embedding_provider(settings)
