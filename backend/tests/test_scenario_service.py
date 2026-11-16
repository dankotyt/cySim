"""Tests for room generation, batch runs and scenario CRUD."""
import pytest

from app.models.department import Department
from app.models.document import SecurityRule
from app.models.scenario import (
    BatchGenerateRequest,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
)
from app.repositories.department_repository import DepartmentRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.security_rule_repository import SecurityRuleRepository
from app.services.scenario_service import (
    DepartmentNotFoundError,
    RuleNotFoundError,
    ScenarioNotFoundError,
    ScenarioService,
)
from tests.fakes import FakeLLMProvider


class _BrokenGenerator:
    """Generator stub that always fails, to exercise the batch error path."""

    async def generate(self, **kwargs):
        raise RuntimeError("llm is down")


def _rule(**overrides):
    defaults = dict(
        description="Запрещено передавать учётные данные третьим лицам.",
        topic="phishing",
        audience=["general"],
        document_id="doc-1",
    )
    defaults.update(overrides)
    return SecurityRule(**defaults)


async def _seed_rules(session, tenant_id="acme", topics=("phishing",)):
    rules = [
        _rule(
            topic=topic,
            description=(
                f"Правило {index}: запрещено передавать учётные данные "
                "третьим лицам."
            ),
        )
        for index, topic in enumerate(topics, start=1)
    ]
    return await SecurityRuleRepository().create_many(session, tenant_id, rules)


def _service(llm=None):
    return ScenarioService(
        rule_repository=SecurityRuleRepository(),
        llm_provider=llm or FakeLLMProvider(),
    )


async def test_generate_scenario_persists_a_room(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)

    response = await service.generate_scenario(db_session, request)

    assert isinstance(response, GenerateScenarioResponse)
    assert response.status == "generated"
    assert response.scenario.room.v == 1
    assert response.scenario.room.goal == "report(o1)"
    assert response.scenario.room.title
    assert response.scenario.topic == "phishing"
    assert response.scenario.tenant_id == "acme"
    assert response.scenario.max_points == 14
    assert response.scenario.corpus_build_id == "fx"
    assert len(response.scenario.fingerprint) == 64

    stored = await service.get_scenario(db_session, response.scenario_id, "acme")
    assert stored.room == response.scenario.room


async def test_generate_scenario_captures_rule_snapshot(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)

    response = await service.generate_scenario(db_session, request)

    snapshot = response.scenario.rule_snapshot
    assert snapshot is not None
    assert snapshot.id == rule.id
    assert snapshot.description == rule.description
    assert snapshot.topic == rule.topic
    assert snapshot.audience == ["general"]
    assert snapshot.document_id == "doc-1"


async def test_generate_scenario_unknown_rule_raises(db_session):
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", rule_id="missing")

    with pytest.raises(RuleNotFoundError):
        await service.generate_scenario(db_session, request)


async def test_generate_scenario_rejects_foreign_tenant(db_session):
    [rule] = await _seed_rules(db_session, tenant_id="acme")
    service = _service()
    request = GenerateScenarioRequest(tenant_id="other", rule_id=rule.id)

    with pytest.raises(RuleNotFoundError):
        await service.generate_scenario(db_session, request)


async def test_generate_scenario_retries_on_invalid_json(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service(llm=FakeLLMProvider(responses=["not-json"]))
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)

    response = await service.generate_scenario(db_session, request)

    assert len(service.llm_provider.calls) == 2  # initial + one retry
    assert response.status == "generated"


async def test_generate_scenario_falls_back_when_llm_keeps_failing(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service(llm=FakeLLMProvider(responses=["bad", "bad", "bad"]))
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)

    response = await service.generate_scenario(db_session, request)

    assert len(service.llm_provider.calls) == 3
    assert response.status == "fallback"
    assert response.scenario.room.goal.startswith("report(")
    assert response.scenario.room.v == 1


async def test_generate_all_scenarios_generates_one_per_rule(db_session):
    await _seed_rules(db_session, topics=("phishing", "internet"))
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 2
    assert response.total_skipped == 0
    assert response.errors == []
    assert sorted(s.topic for s in response.generated) == ["internet", "phishing"]


async def test_batch_does_not_repeat_the_same_room(db_session):
    await _seed_rules(db_session, topics=("phishing", "phishing"))
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    fingerprints = {scenario.fingerprint for scenario in response.generated}
    assert response.total_generated == 2
    assert len(fingerprints) == 2


async def test_generate_all_scenarios_skips_when_no_rules(db_session):
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 0
    assert response.total_skipped == 1
    assert response.skipped == ["all"]
    assert response.errors == []
    assert service.llm_provider.calls == []


async def test_generate_all_scenarios_topic_filter(db_session):
    await _seed_rules(db_session, topics=("phishing", "internet"))
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme", topic="phishing")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 1
    assert response.total_skipped == 0
    assert [s.topic for s in response.generated] == ["phishing"]


async def test_generate_all_scenarios_filters_by_department(db_session):
    await _seed_rules(db_session, topics=("phishing", "internet"))
    await DepartmentRepository().create(
        db_session,
        Department(tenant_id="acme", name="hr", allowed_topics=["internet"]),
    )

    service = _service()
    request = BatchGenerateRequest(tenant_id="acme", department="hr")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 1
    assert [s.topic for s in response.generated] == ["internet"]


async def test_generate_all_scenarios_unknown_department_raises(db_session):
    await _seed_rules(db_session)
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme", department="nope")

    with pytest.raises(DepartmentNotFoundError):
        await service.generate_all_scenarios(db_session, request)


async def test_generate_all_scenarios_records_errors(db_session):
    await _seed_rules(db_session)
    service = _service()
    service.room_generator = _BrokenGenerator()
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 0
    assert response.total_skipped == 0
    assert any(error["topic"] == "phishing" for error in response.errors)


async def test_get_scenario_not_found(db_session):
    service = _service()

    with pytest.raises(ScenarioNotFoundError):
        await service.get_scenario(db_session, "missing")


async def test_public_scenario_hides_the_answer_key(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service()
    created = await service.generate_scenario(
        db_session, GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)
    )

    public = await service.get_public_scenario(
        db_session, created.scenario_id, "acme"
    )

    payload = public.model_dump()
    assert "goal" not in payload
    assert public.title
    assert public.objs[0].ref == "fx:email:em-0001"


async def test_list_and_delete(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)
    created = await service.generate_scenario(db_session, request)

    assert len(await service.list_scenarios(db_session, "acme")) == 1

    await service.delete_scenario(db_session, created.scenario_id)
    assert await service.list_scenarios(db_session, "acme") == []

    history = await service.list_scenarios(db_session, "acme", include_deleted=True)
    assert [scenario.id for scenario in history] == [created.scenario_id]


async def test_soft_deleted_rule_hides_scenarios_but_keeps_history(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)
    created = await service.generate_scenario(db_session, request)

    await SecurityRuleRepository().delete(db_session, rule.id)
    await ScenarioRepository().soft_delete_by_rule_ids(db_session, [rule.id])

    with pytest.raises(RuleNotFoundError):
        await service.generate_scenario(db_session, request)
    with pytest.raises(ScenarioNotFoundError):
        await service.get_scenario(db_session, created.scenario_id, "acme")

    assert await service.list_scenarios(db_session, "acme") == []
    history = await service.list_scenarios(db_session, "acme", include_deleted=True)
    assert [scenario.id for scenario in history] == [created.scenario_id]
    assert history[0].rule_snapshot is not None
    assert history[0].rule_snapshot.description == rule.description
