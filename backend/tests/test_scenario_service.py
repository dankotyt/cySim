"""Tests for the scenario generation service."""
import pytest

from app.models.document import SecurityRule
from app.models.scenario import (
    BatchGenerateRequest,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
)
from app.repositories.security_rule_repository import SecurityRuleRepository
from app.services.scenario_service import (
    NoRulesFoundError,
    ScenarioNotFoundError,
    ScenarioService,
)
from tests.fakes import FakeLLMProvider


def _rule(**overrides):
    defaults = dict(
        title="Не передавать пароли",
        description="Запрещено передавать учётные данные третьим лицам.",
        attack_type="phishing",
        source="policy.txt",
        page=1,
        score=0.9,
    )
    defaults.update(overrides)
    return SecurityRule(**defaults)


async def _seed_rules(
    session, tenant_id="acme", categories=("phishing",), document_id="doc-1"
):
    rules = [_rule(attack_type=category) for category in categories]
    await SecurityRuleRepository().create_many(
        session, tenant_id, document_id, rules
    )
    return rules


def _service(llm=None):
    return ScenarioService(
        rule_repository=SecurityRuleRepository(),
        llm_provider=llm or FakeLLMProvider(),
    )


async def test_generate_scenario_persists_and_returns(db_session):
    await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", attack_type="phishing")

    response = await service.generate_scenario(db_session, request)

    assert isinstance(response, GenerateScenarioResponse)
    assert response.scenario_id
    assert response.status == "generated"
    assert response.scenario.title
    assert response.scenario.attack_type == "phishing"
    assert response.scenario.tenant_id == "acme"

    stored = await service.get_scenario(db_session, response.scenario_id, "acme")
    assert stored.id == response.scenario_id


async def test_generate_scenario_no_rules_raises(db_session):
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", attack_type="phishing")

    with pytest.raises(NoRulesFoundError):
        await service.generate_scenario(db_session, request)


async def test_generate_scenario_limits_rules_for_llm(db_session):
    rules = [
        _rule(attack_type="phishing", description=f"Запрет {index}.")
        for index in range(1, 8)
    ]
    await SecurityRuleRepository().create_many(db_session, "acme", "doc-1", rules)

    service = _service()
    request = GenerateScenarioRequest(
        tenant_id="acme", attack_type="phishing", top_k_rules=3
    )
    response = await service.generate_scenario(db_session, request)

    prompt = service.llm_provider.calls[0]
    assert prompt.count("Название:") == 3  # only top_k rules reach the LLM
    assert response.scenario.attack_type == "phishing"


async def test_generate_scenario_retries_on_invalid_json(db_session):
    await _seed_rules(db_session)
    service = _service(llm=FakeLLMProvider(responses=["not-json"]))
    request = GenerateScenarioRequest(tenant_id="acme", attack_type="phishing")

    response = await service.generate_scenario(db_session, request)

    assert len(service.llm_provider.calls) == 2  # initial + one clarification retry
    assert response.scenario.title


async def test_generate_all_scenarios(db_session):
    await _seed_rules(db_session, categories=("phishing",))
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme", top_k_rules=5)

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 1
    assert response.total_skipped == 7  # 8 attack types - 1 with rules
    assert response.errors == []
    assert [s.attack_type for s in response.generated] == ["phishing"]
    assert "vishing" in response.skipped


async def test_generate_all_scenarios_records_errors(db_session):
    await _seed_rules(db_session, categories=("phishing",))
    service = _service(llm=FakeLLMProvider(responses=["bad", "bad"]))
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 0
    assert response.total_skipped == 7
    assert any(error["attack_type"] == "phishing" for error in response.errors)


async def test_get_scenario_not_found(db_session):
    service = _service()

    with pytest.raises(ScenarioNotFoundError):
        await service.get_scenario(db_session, "missing")


async def test_list_and_delete(db_session):
    await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", attack_type="phishing")
    created = await service.generate_scenario(db_session, request)

    assert len(await service.list_scenarios(db_session, "acme")) == 1

    await service.delete_scenario(db_session, created.scenario_id)
    assert await service.list_scenarios(db_session, "acme") == []
