"""Tests for the LLM rule structurer."""
from app.models.document import Chunk, DocumentType
from app.services.rule_structurer import ALLOWED_TOPICS, RuleStructurer
from tests.fakes import FakeEmbeddingProvider, FakeLLMProvider


def _chunk(text):
    return Chunk(
        id="1",
        document_id="doc-1",
        text=text,
        page=1,
        chunk_index=0,
        source="policy.txt",
        document_type=DocumentType.TXT,
    )


def _structurer(llm=None):
    return RuleStructurer(
        llm_provider=llm or FakeLLMProvider(),
        embedding_provider=FakeEmbeddingProvider(),
        batch_size=5,
    )


def test_allowed_topics_count():
    assert 15 <= len(ALLOWED_TOPICS) <= 20


def test_validate_rejects_unknown_topic():
    structurer = _structurer()
    valid = structurer._is_valid(
        {"topic": "made_up_topic", "description": "текст"}, [_chunk("текст")]
    )
    assert valid is False


def test_validate_rejects_hallucinated_description():
    structurer = _structurer()
    valid = structurer._is_valid(
        {"topic": "phishing", "description": "выдуманный текст"},
        [_chunk("совсем другой текст")],
    )
    assert valid is False


def test_validate_accepts_valid_rule():
    structurer = _structurer()
    chunk = _chunk("Пароль должен содержать 12 символов.")
    valid = structurer._is_valid(
        {"topic": "passwords", "description": "Пароль должен содержать 12 символов."},
        [chunk],
    )
    assert valid is True


def test_structure_end_to_end():
    response = (
        '{"rules": [{"title": "Сложные пароли", '
        '"description": "Пароль должен содержать 12 символов.", '
        '"section": "Пароли", "topic": "passwords", "linked_docs": []}]}'
    )
    structurer = _structurer(llm=FakeLLMProvider(responses=[response]))

    rules = structurer.structure(
        [_chunk("Пароль должен содержать 12 символов.")], "acme", "doc-1"
    )

    assert len(rules) == 1
    assert rules[0].topic == "passwords"
    assert rules[0].document_id == "doc-1"
    assert rules[0].section == "Пароли"
