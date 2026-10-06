"""Shared test doubles."""
import hashlib

from app.models.document import SecurityRule
from app.services.document_validator import DocumentValidationError
from app.services.llm_provider import LLMProvider
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


VALID_SCENARIO_JSON = (
    '{"title": "Фишинг-тест", '
    '"context": {"company_rule": "Правило 1 [phishing]", "source": "policy.txt", "page": 1}, '
    '"steps": [{"step_id": "1", "type": "email_view", "content": "Письмо с вложением", '
    '"actions": [{"id": "a", "label": "Открыть", "is_correct": false, "consequence": "Заражение", "points": 0}, '
    '{"id": "b", "label": "Сообщить в СБ", "is_correct": true, "consequence": "Локализовано", "points": 10}], '
    '"feedback": "Правильно", "correct_action": "b"}], '
    '"scoring": {"max_points": 10, "passing_score": 7}}'
)


class FakeLLMProvider(LLMProvider):
    """Deterministic LLM provider that returns canned responses in order."""

    name = "fake"

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses) if responses else []
        self.calls: list[str] = []

    def generate(self, prompt: str, **kwargs) -> str:
        self.calls.append(prompt)
        if self._responses:
            return self._responses.pop(0)
        return VALID_SCENARIO_JSON

    def is_available(self) -> bool:
        return True


class FakeRuleStructurer:
    """Deterministic rule structurer that returns one canned rule."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def structure(self, chunks, tenant_id, document_id):
        self.calls.append((chunks, tenant_id, document_id))
        return [
            SecurityRule(
                title="Не передавать пароли",
                description="Пароль должен содержать 12 символов.",
                section="Пароли",
                topic="passwords",
                linked_docs=[],
                document_id=document_id,
            )
        ]
