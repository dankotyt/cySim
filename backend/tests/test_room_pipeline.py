"""Generation pipeline: retries, structural dedup and the fallback room."""
import json

import pytest

from app.core.intents import INTENTS
from app.models.document import SecurityRule
from app.models.scenario import Room
from app.services.scenario_generation import (
    RoomGenerator,
    get_resources,
    room_fingerprint,
    validate_room,
)
from tests.fakes import VALID_ROOM, FakeLLMProvider

INTENT = "attachment_macro"


def _rule(topic: str = "phishing", intent: str = INTENT) -> SecurityRule:
    return SecurityRule(
        description="Сообщать о подозрительных письмах в службу безопасности.",
        topic=topic,
        intent=intent,
        audience=["general"],
        document_id="doc-1",
    )


def _duplicate_fingerprint() -> str:
    room = Room.model_validate({"topic": "phishing", **VALID_ROOM})
    return room_fingerprint(room)


async def test_valid_answer_is_accepted_on_the_first_attempt():
    generator = RoomGenerator(FakeLLMProvider())

    result = await generator.generate(
        rule=_rule(),
        intent=INTENT,
        benign=False,
        tenant_id="acme",
        department="default",
    )

    assert result.source == "llm"
    assert result.attempts == 1
    assert validate_room(
        result.room, intent=INTENT, benign=False, resources=get_resources()
    ).ok


async def test_invalid_json_triggers_a_retry():
    llm = FakeLLMProvider(responses=["это не json"])
    generator = RoomGenerator(llm)

    result = await generator.generate(
        rule=_rule(),
        intent=INTENT,
        benign=False,
        tenant_id="acme",
        department="default",
    )

    assert result.source == "llm"
    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert "Исправь ошибки предыдущего ответа" in llm.calls[1]


async def test_three_failures_produce_a_valid_fallback_room():
    llm = FakeLLMProvider(responses=["bad", "bad", "bad"])
    generator = RoomGenerator(llm)

    result = await generator.generate(
        rule=_rule(),
        intent=INTENT,
        benign=False,
        tenant_id="acme",
        department="default",
    )

    assert result.source == "fallback"
    assert result.attempts == 3
    assert result.room.intent == INTENT
    assert "В работе появился объект" not in result.room.brief
    assert result.room.brief.endswith("?")
    assert validate_room(
        result.room, intent=INTENT, benign=False, resources=get_resources()
    ).ok
    assert len(llm.calls) == 3


async def test_benign_intent_produces_a_dismiss_goal():
    generator = RoomGenerator(FakeLLMProvider(responses=["bad"] * 3))

    result = await generator.generate(
        rule=_rule(),
        intent=INTENT,
        benign=True,
        tenant_id="acme",
        department="default",
    )

    assert result.source == "fallback"
    assert result.room.goal == "dismiss(o1)"
    assert validate_room(
        result.room, intent=INTENT, benign=True, resources=get_resources()
    ).ok


async def test_structural_duplicate_is_rejected():
    llm = FakeLLMProvider()
    generator = RoomGenerator(llm)

    result = await generator.generate(
        rule=_rule(),
        intent=INTENT,
        benign=False,
        tenant_id="acme",
        department="default",
        recent_fingerprints={_duplicate_fingerprint()},
    )

    assert result.source == "fallback"
    assert result.attempts == 2  # второй дубликат сразу уводит в fallback
    assert len(llm.calls) == 2
    assert "L4 duplicate" in llm.calls[1]
    assert "objs=[" in llm.calls[1]
    assert room_fingerprint(result.room) != _duplicate_fingerprint()


async def test_retry_prompt_includes_the_rejected_room():
    invalid = json.dumps(
        {**VALID_ROOM, "goal": "!report(o1)"}, ensure_ascii=False
    )
    llm = FakeLLMProvider(responses=[invalid])
    generator = RoomGenerator(llm)

    result = await generator.generate(
        rule=_rule(),
        intent=INTENT,
        benign=False,
        tenant_id="acme",
        department="default",
    )

    assert result.source == "llm"
    assert len(llm.calls) == 2
    assert "Отклонённая комната" in llm.calls[1]
    assert "!report(o1)" in llm.calls[1]


async def test_fallback_covers_every_intent():
    resources = get_resources()
    for intent in INTENTS:
        result = await RoomGenerator(FakeLLMProvider(responses=["bad"] * 3)).generate(
            rule=_rule(intent=intent),
            intent=intent,
            benign=False,
            tenant_id="acme",
            department="default",
        )
        validation = validate_room(
            result.room, intent=intent, benign=False, resources=resources
        )
        assert validation.ok, f"{intent}: {validation.summary()}"


async def test_physical_intent_fallback_uses_a_workstation():
    intent = "unattended_session"
    result = await RoomGenerator(FakeLLMProvider(responses=["bad"] * 3)).generate(
        rule=_rule(intent=intent),
        intent=intent,
        benign=False,
        tenant_id="acme",
        department="default",
    )

    assert result.room.objs[0].kind == "workstation"
    assert result.room.goal == "lock(o1)"
    assert validate_room(
        result.room, intent=intent, benign=False, resources=get_resources()
    ).ok


@pytest.mark.parametrize(
    "payload",
    [
        {"v": 4},
        {"goal": "report(o1) &&"},
        {"objs": []},
    ],
)
async def test_malformed_payloads_are_rejected(payload):
    raw = json.dumps({**VALID_ROOM, **payload}, ensure_ascii=False)
    generator = RoomGenerator(FakeLLMProvider(responses=[raw] * 3))

    result = await generator.generate(
        rule=_rule(),
        intent=INTENT,
        benign=False,
        tenant_id="acme",
        department="default",
    )

    assert result.source == "fallback"
    assert result.problems
