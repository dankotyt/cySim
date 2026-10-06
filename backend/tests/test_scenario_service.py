"""Tests for the scenario generation service."""
import pytest

from app.models.department import Department
from app.models.document import SecurityRule
from app.models.scenario import (
    ATTACK_TYPES,
    BatchGenerateRequest,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
)
from app.repositories.department_repository import DepartmentRepository
from app.repositories.security_rule_repository import SecurityRuleRepository
from app.services.scenario_service import (
    DepartmentNotFoundError,
    NoRulesFoundError,
    ScenarioNotFoundError,
    ScenarioService,
)
from tests.fakes import FakeEmbeddingProvider, FakeLLMProvider


def _rule(**overrides):
    defaults = dict(
        title="Не передавать пароли",
        description="Запрещено передавать учётные данные третьим лицам.",
        section="Пароли",
        topic="phishing",
        linked_docs=[],
        document_id="doc-1",
    )
    defaults.update(overrides)
    return SecurityRule(**defaults)


async def _seed_rules(session, tenant_id="acme", topics=("phishing",), document_id="doc-1"):
    rules = [_rule(topic=topic, document_id=document_id) for topic in topics]
    await SecurityRuleRepository().create_many(session, tenant_id, rules)
    return rules


def _service(llm=None):
    return ScenarioService(
        rule_repository=SecurityRuleRepository(),
        llm_provider=llm or FakeLLMProvider(),
        embedding_provider=FakeEmbeddingProvider(),
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
    assert response.scenario.department == "default"
    assert response.scenario.topics_used == ["phishing"]

    stored = await service.get_scenario(db_session, response.scenario_id, "acme")
    assert stored.id == response.scenario_id
    assert stored.department == "default"
    assert stored.topics_used == ["phishing"]


async def test_generate_scenario_no_rules_raises(db_session):
    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", attack_type="phishing")

    with pytest.raises(NoRulesFoundError):
        await service.generate_scenario(db_session, request)


async def test_generate_scenario_passes_all_rules_without_top_k(db_session):
    rules = [
        _rule(topic="phishing", description=f"Запрет {index}.")
        for index in range(1, 8)
    ]
    await SecurityRuleRepository().create_many(db_session, "acme", rules)

    service = _service()
    request = GenerateScenarioRequest(tenant_id="acme", attack_type="phishing")
    response = await service.generate_scenario(db_session, request)

    prompt = service.llm_provider.calls[0]
    assert prompt.count("Название:") == 7  # every rule reaches the LLM
    assert response.scenario.attack_type == "phishing"


async def test_generate_scenario_filters_by_department(db_session):
    await SecurityRuleRepository().create_many(
        db_session,
        "acme",
        [
            _rule(
                topic="phishing",
                description="Сообщать о подозрительных письмах в СБ.",
            ),
            _rule(
                topic="passwords",
                description="Пароль должен содержать 12 символов.",
            ),
        ],
    )
    await DepartmentRepository().create(
        db_session,
        Department(tenant_id="acme", name="hr", allowed_topics=["passwords"]),
    )

    service = _service()
    request = GenerateScenarioRequest(
        tenant_id="acme", attack_type="phishing", department="hr"
    )
    response = await service.generate_scenario(db_session, request)

    prompt = service.llm_provider.calls[0]
    assert "Пароль должен содержать 12 символов" in prompt
    assert "Сообщать о подозрительных письмах в СБ" not in prompt
    assert response.scenario.department == "hr"
    assert response.scenario.topics_used == ["passwords"]


async def test_generate_scenario_unknown_department_raises(db_session):
    await _seed_rules(db_session)
    service = _service()
    request = GenerateScenarioRequest(
        tenant_id="acme", attack_type="phishing", department="nope"
    )

    with pytest.raises(DepartmentNotFoundError):
        await service.generate_scenario(db_session, request)


async def test_generate_scenario_department_no_rules_raises(db_session):
    await _seed_rules(db_session, topics=("phishing",))
    await DepartmentRepository().create(
        db_session,
        Department(tenant_id="acme", name="hr", allowed_topics=["passwords"]),
    )

    service = _service()
    request = GenerateScenarioRequest(
        tenant_id="acme", attack_type="phishing", department="hr"
    )

    with pytest.raises(NoRulesFoundError):
        await service.generate_scenario(db_session, request)


async def test_generate_scenario_retries_on_invalid_json(db_session):
    await _seed_rules(db_session)
    service = _service(llm=FakeLLMProvider(responses=["not-json"]))
    request = GenerateScenarioRequest(tenant_id="acme", attack_type="phishing")

    response = await service.generate_scenario(db_session, request)

    assert len(service.llm_provider.calls) == 2  # initial + one clarification retry
    assert response.scenario.title


async def test_generate_all_scenarios_generates_for_each_type(db_session):
    await _seed_rules(db_session, topics=("phishing",))
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 8
    assert response.total_skipped == 0
    assert response.errors == []
    assert sorted(s.attack_type for s in response.generated) == sorted(ATTACK_TYPES)


async def test_generate_all_scenarios_skips_when_no_rules(db_session):
    service = _service()
    request = BatchGenerateRequest(tenant_id="acme")

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 0
    assert response.total_skipped == 8
    assert response.errors == []


async def test_generate_all_scenarios_respects_attack_types(db_session):
    await _seed_rules(db_session, topics=("phishing",))
    service = _service()
    request = BatchGenerateRequest(
        tenant_id="acme", attack_types=["phishing", "vishing"]
    )

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 2
    assert response.total_skipped == 0
    assert sorted(s.attack_type for s in response.generated) == ["phishing", "vishing"]


async def test_generate_all_scenarios_records_errors(db_session):
    await _seed_rules(db_session, topics=("phishing",))
    service = _service(llm=FakeLLMProvider(responses=["bad", "bad"]))
    request = BatchGenerateRequest(tenant_id="acme", attack_types=["phishing"])

    response = await service.generate_all_scenarios(db_session, request)

    assert response.total_generated == 0
    assert response.total_skipped == 0
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
