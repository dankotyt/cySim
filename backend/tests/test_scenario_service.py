"""Tests for the scenario generation service."""
import pytest

from app.models.department import Department
from app.models.document import SecurityRule
from app.models.scenario import (
    BatchGenerateRequest,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
)
from app.repositories.department_repository import DepartmentRepository
from app.repositories.security_rule_repository import SecurityRuleRepository
from app.services.scenario_service import (
    DepartmentNotFoundError,
    RuleNotFoundError,
    ScenarioNotFoundError,
    ScenarioService,
)
from tests.fakes import FakeLLMProvider


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
    rules = [_rule(topic=topic) for topic in topics]
    await SecurityRuleRepository().create_many(session, tenant_id, rules)
    return rules


def _service(llm=None):
    return ScenarioService(
        rule_repository=SecurityRuleRepository(),
        llm_provider=llm or FakeLLMProvider(),
    )


async def test_generate_scenario_persists_and_returns(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)

    response = await service.generate_scenario(db_session, request)

    assert isinstance(response, GenerateScenarioResponse)
    assert response.scenario_id
    assert response.status == "generated"
    assert response.scenario.title
    assert response.scenario.topic == "phishing"
    assert response.scenario.tenant_id == "acme"
    assert response.scenario.department == "default"

    stored = await service.get_scenario(db_session, response.scenario_id, "acme")
    assert stored.id == response.scenario_id
    assert stored.topic == "phishing"


async def test_generate_scenario_unknown_rule_raises(db_session):
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", rule_id="missing")

    with pytest.raises(RuleNotFoundError):
        await service.generate_scenario(db_session, request)


async def test_generate_scenario_retries_on_invalid_json(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service(llm=FakeLLMProvider(responses=["not-json"]))
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)

    response = await service.generate_scenario(db_session, request)

    assert len(service.llm_provider.calls) == 2  # initial + one retry
    assert response.scenario.title


async def test_generate_all_scenarios_generates_one_per_rule(db_session):
    await _seed_rules(db_session, topics=("phishing", "internet"))
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 2
    assert response.total_skipped == 0
    assert response.errors == []
    assert sorted(s.topic for s in response.generated) == ["internet", "phishing"]


async def test_generate_all_scenarios_skips_when_no_rules(db_session):
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 0
    assert response.total_skipped == 1
    assert response.skipped == ["all"]
    assert response.errors == []


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
    assert response.total_skipped == 0


async def test_generate_all_scenarios_unknown_department_raises(db_session):
    await _seed_rules(db_session)
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme", department="nope")

    with pytest.raises(DepartmentNotFoundError):
        await service.generate_all_scenarios(db_session, request)


async def test_generate_all_scenarios_records_errors(db_session):
    await _seed_rules(db_session, topics=("phishing",))
    service = _service(llm=FakeLLMProvider(responses=["bad", "bad"]))
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 0
    assert response.total_skipped == 0
    assert any(error["topic"] == "phishing" for error in response.errors)


async def test_get_scenario_not_found(db_session):
    service = _service()

    with pytest.raises(ScenarioNotFoundError):
        await service.get_scenario(db_session, "missing")


async def test_list_and_delete(db_session):
    [rule] = await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", rule_id=rule.id)
    created = await service.generate_scenario(db_session, request)

    assert len(await service.list_scenarios(db_session, "acme")) == 1

    await service.delete_scenario(db_session, created.scenario_id)
    assert await service.list_scenarios(db_session, "acme") == []
