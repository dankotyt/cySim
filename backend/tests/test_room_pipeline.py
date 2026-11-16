"""Generation pipeline: retries, structural dedup and the fallback room."""
import pytest

from app.models.document import SecurityRule
from app.models.scenario import Room
from app.services.scenario_generation import (
    RoomGenerator,
    get_resources,
    room_fingerprint,
    validate_room,
)
from tests.fakes import VALID_ROOM, FakeLLMProvider


def _rule(topic: str = "phishing") -> SecurityRule:
    return SecurityRule(
        description="Сообщать о подозрительных письмах в службу безопасности.",
        topic=topic,
        audience=["general"],
        document_id="doc-1",
    )


def _duplicate_fingerprint() -> str:
    room = Room.model_validate({"topic": "phishing", **VALID_ROOM})
    return room_fingerprint(room)


async def test_valid_answer_is_accepted_on_the_first_attempt():
    generator = RoomGenerator(FakeLLMProvider())

    result = await generator.generate(
        rule=_rule(), tenant_id="acme", department="default"
    )

    assert result.source == "llm"
    assert result.attempts == 1
    assert validate_room(
        result.room, rule_topic="phishing", resources=get_resources()
    ).ok


async def test_invalid_json_triggers_a_retry():
    llm = FakeLLMProvider(responses=["это не json"])
    generator = RoomGenerator(llm)

    result = await generator.generate(
        rule=_rule(), tenant_id="acme", department="default"
    )

    assert result.source == "llm"
    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert "Исправь ошибки предыдущего ответа" in llm.calls[1]


async def test_three_failures_produce_a_valid_fallback_room():
    llm = FakeLLMProvider(responses=["bad", "bad", "bad"])
    generator = RoomGenerator(llm)

    result = await generator.generate(
        rule=_rule(), tenant_id="acme", department="default"
    )

    assert result.source == "fallback"
    assert result.attempts == 3
    assert validate_room(
        result.room, rule_topic="phishing", resources=get_resources()
    ).ok
    assert len(llm.calls) == 3


async def test_structural_duplicate_is_rejected():
    generator = RoomGenerator(FakeLLMProvider())

    result = await generator.generate(
        rule=_rule(),
        tenant_id="acme",
        department="default",
        recent_fingerprints={_duplicate_fingerprint()},
    )

    assert result.source == "fallback"
    assert room_fingerprint(result.room) != _duplicate_fingerprint()


async def test_fallback_covers_every_rule_topic():
    from app.core.topics import ALLOWED_TOPICS

    resources = get_resources()
    for topic in ALLOWED_TOPICS:
        result = await RoomGenerator(FakeLLMProvider(responses=["bad"] * 3)).generate(
            rule=_rule(topic), tenant_id="acme", department="default"
        )
        validation = validate_room(
            result.room, rule_topic=topic, resources=resources
        )
        assert validation.ok, f"{topic}: {validation.summary()}"


@pytest.mark.parametrize(
    "payload",
    [
        {"v": 4},
        {"goal": "report(o1) &&"},
        {"objs": []},
    ],
)
async def test_malformed_payloads_are_rejected(payload):
    import json

    raw = json.dumps({**VALID_ROOM, **payload}, ensure_ascii=False)
    generator = RoomGenerator(FakeLLMProvider(responses=[raw] * 3))

    result = await generator.generate(
        rule=_rule(), tenant_id="acme", department="default"
    )

    assert result.source == "fallback"
    assert result.problems
