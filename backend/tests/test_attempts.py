"""Trainee attempts: event log, scoring, closure and tenant isolation."""
import pytest

from app.models.document import SecurityRule
from app.models.scenario import (
    Room,
    RuleSnapshot,
    Scenario,
    max_points_for,
)
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.security_rule_repository import SecurityRuleRepository
from app.services.scenario_generation import room_fingerprint
from app.services.scenario_service import (
    AttemptClosedError,
    AttemptNotFoundError,
    ScenarioNotFoundError,
    ScenarioService,
)
from tests.fakes import VALID_ROOM, FakeLLMProvider


async def _seed_scenario(session, tenant_id="acme") -> Scenario:
    rule = SecurityRule(
        description="Сообщать о подозрительных письмах в службу безопасности.",
        topic="phishing",
        audience=["general"],
        document_id="doc-1",
    )
    [created] = await SecurityRuleRepository().create_many(
        session, tenant_id, [rule]
    )
    room = Room.model_validate({**VALID_ROOM, "topic": "phishing"})
    scenario = Scenario(
        id="sc-1",
        tenant_id=tenant_id,
        rule_snapshot=RuleSnapshot(
            id=created.id,
            description=created.description,
            topic=created.topic,
            audience=["general"],
            document_id="doc-1",
        ),
        topic="phishing",
        corpus_build_id="fx",
        fingerprint=room_fingerprint(room),
        max_points=max_points_for(room.diff),
        room=room,
    )
    await ScenarioRepository().create(session, scenario)
    return scenario


def _service() -> ScenarioService:
    return ScenarioService(llm_provider=FakeLLMProvider())


async def test_start_attempt_returns_an_empty_state(db_session):
    scenario = await _seed_scenario(db_session)
    service = _service()

    attempt = await service.start_attempt(
        db_session, scenario.id, "acme", "emp-1"
    )
    state = await service.attempt_state(db_session, attempt.id, "acme")

    assert state.outcome == "in_progress"
    assert state.score is None
    assert state.events == []
    assert state.max_points == 14
    assert state.employee_id == "emp-1"


async def test_actions_are_evaluated_and_close_the_attempt(db_session):
    scenario = await _seed_scenario(db_session)
    service = _service()
    attempt = await service.start_attempt(
        db_session, scenario.id, "acme", "emp-1"
    )

    await service.submit_event(db_session, attempt.id, "acme", "inspect", "o1")
    finished = await service.submit_event(
        db_session, attempt.id, "acme", "report", "o1"
    )

    assert finished.outcome == "safe"
    assert finished.score == 14
    assert finished.finished_at is not None

    state = await service.attempt_state(db_session, attempt.id, "acme")
    assert [event.verb for event in state.events] == ["inspect", "report"]
    assert state.lessons == []


async def test_soft_trap_returns_a_lesson(db_session):
    scenario = await _seed_scenario(db_session)
    service = _service()
    attempt = await service.start_attempt(
        db_session, scenario.id, "acme", "emp-1"
    )

    await service.submit_event(db_session, attempt.id, "acme", "inspect", "o1")
    await service.submit_event(db_session, attempt.id, "acme", "reply", "o1")
    finished = await service.submit_event(
        db_session, attempt.id, "acme", "report", "o1"
    )

    assert finished.outcome == "recovered"
    assert finished.score == 12

    state = await service.attempt_state(db_session, attempt.id, "acme")
    assert [lesson.id for lesson in state.lessons] == ["L_REPLY_TO"]
    assert state.lessons[0].text


async def test_hard_trap_compromises_the_attempt(db_session):
    scenario = await _seed_scenario(db_session)
    service = _service()
    attempt = await service.start_attempt(
        db_session, scenario.id, "acme", "emp-1"
    )

    finished = await service.submit_event(
        db_session, attempt.id, "acme", "download", "o1"
    )

    assert finished.outcome == "compromised"
    assert finished.score == 4


async def test_event_after_completion_is_rejected(db_session):
    scenario = await _seed_scenario(db_session)
    service = _service()
    attempt = await service.start_attempt(
        db_session, scenario.id, "acme", "emp-1"
    )
    await service.submit_event(db_session, attempt.id, "acme", "report", "o1")

    with pytest.raises(AttemptClosedError):
        await service.submit_event(db_session, attempt.id, "acme", "report", "o1")


async def test_attempt_is_scoped_to_its_tenant(db_session):
    scenario = await _seed_scenario(db_session)
    service = _service()
    attempt = await service.start_attempt(
        db_session, scenario.id, "acme", "emp-1"
    )

    with pytest.raises(AttemptNotFoundError):
        await service.attempt_state(db_session, attempt.id, "other")
    with pytest.raises(ScenarioNotFoundError):
        await service.start_attempt(db_session, scenario.id, "other", "emp-1")


async def test_state_survives_soft_deleted_scenario(db_session):
    scenario = await _seed_scenario(db_session)
    service = _service()
    attempt = await service.start_attempt(
        db_session, scenario.id, "acme", "emp-1"
    )
    await service.submit_event(db_session, attempt.id, "acme", "inspect", "o1")
    await service.submit_event(db_session, attempt.id, "acme", "report", "o1")

    await service.delete_scenario(db_session, scenario.id)
    state = await service.attempt_state(db_session, attempt.id, "acme")

    assert state.outcome == "safe"
    assert state.score == 14


async def test_attempts_are_listed_per_employee(db_session):
    scenario = await _seed_scenario(db_session)
    service = _service()
    first = await service.start_attempt(db_session, scenario.id, "acme", "emp-1")
    await service.start_attempt(db_session, scenario.id, "acme", "emp-2")

    states = await service.list_attempt_states(
        db_session, "acme", employee_id="emp-1"
    )

    assert [state.attempt_id for state in states] == [first.id]
