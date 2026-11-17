"""Intent classification and catalog invariants."""
import json

import pytest

from app.core.intents import INTENTS, NOT_REPRESENTABLE
from app.models.document import SecurityRule
from app.services.scenario_generation.classifier import (
    IntentClassificationError,
    RuleIntentClassifier,
)
from tests.fakes import FakeLLMProvider


def _rule(description: str = "Сотрудник блокирует экран при отходе.") -> SecurityRule:
    return SecurityRule(
        description=description,
        topic="passwords",
        audience=["general"],
        document_id="doc-1",
    )


async def test_classifier_returns_a_known_intent_and_corrected_topic():
    llm = FakeLLMProvider(
        responses=[
            json.dumps({"intent": "unattended_session", "topic": "physical_security"})
        ]
    )

    result = await RuleIntentClassifier(llm).classify(_rule())

    assert result.intent == "unattended_session"
    assert result.intent in INTENTS
    assert result.topic == "physical_security"


async def test_classifier_allows_not_representable_rules():
    llm = FakeLLMProvider(
        responses=[json.dumps({"intent": NOT_REPRESENTABLE, "topic": "audit"})]
    )

    result = await RuleIntentClassifier(llm).classify(_rule())

    assert result.intent == NOT_REPRESENTABLE
    assert result.topic == "audit"


async def test_classifier_ignores_an_unknown_topic():
    llm = FakeLLMProvider(
        responses=[json.dumps({"intent": "phishing_email", "topic": "made_up"})]
    )

    assert await RuleIntentClassifier(llm).classify(_rule()).topic is None


async def test_classifier_retries_when_a_topic_is_returned_as_intent():
    llm = FakeLLMProvider(
        responses=[
            json.dumps({"intent": "access_control", "topic": "access_control"}),
            json.dumps({"intent": "unattended_session", "topic": "physical_security"}),
        ]
    )

    result = await RuleIntentClassifier(llm).classify(_rule())

    assert result.intent == "unattended_session"
    assert result.topic == "physical_security"
    assert len(llm.calls) == 2
    assert "не входит в список интентов" in llm.calls[1]


async def test_classifier_never_accepts_a_topic_as_intent():
    topic_as_intent = json.dumps(
        {"intent": "access_control", "topic": "access_control"}
    )
    llm = FakeLLMProvider(responses=[topic_as_intent, topic_as_intent])

    with pytest.raises(IntentClassificationError) as exc_info:
        await RuleIntentClassifier(llm).classify(_rule())

    assert exc_info.value.reason == "invalid_intent"
    assert len(llm.calls) == 2


async def test_classifier_rejects_unknown_intent_after_retry():
    unknown = json.dumps({"intent": "screen_locking"})
    llm = FakeLLMProvider(responses=[unknown, unknown])

    with pytest.raises(IntentClassificationError) as exc_info:
        await RuleIntentClassifier(llm).classify(_rule())

    assert exc_info.value.reason == "invalid_intent"
    assert len(llm.calls) == 2


async def test_classifier_rejects_invalid_json_after_retry():
    llm = FakeLLMProvider(responses=["не json", "не json"])

    with pytest.raises(IntentClassificationError) as exc_info:
        await RuleIntentClassifier(llm).classify(_rule())

    assert exc_info.value.reason == "invalid_json"
    assert len(llm.calls) == 2


def test_classifier_prompt_does_not_offer_topics_as_intents():
    from app.services.scenario_generation.classifier import (
        CLASSIFIER_SYSTEM_PROMPT,
    )

    assert "access_control" not in CLASSIFIER_SYSTEM_PROMPT
    assert "email_security" not in CLASSIFIER_SYSTEM_PROMPT


def test_every_intent_has_both_polarities_in_the_registry():
    from app.services.scenario_generation import get_resources

    artifacts = get_resources().artifacts
    missing = [
        (intent, benign)
        for intent in INTENTS
        for benign in (False, True)
        if not artifacts.has_polarity(intent, benign)
    ]

    assert missing == []


def test_every_artifact_has_a_goal_action_available_on_its_kind():
    from app.services.scenario_generation import get_resources
    from app.services.scenario_generation.validators import KIND_VERBS

    for artifact in get_resources().artifacts.all():
        for intent in artifact.intents:
            actions = artifact.goal_actions_for(intent)
            assert actions, f"{artifact.ref} declares no goal for {intent}"
            assert set(actions) <= KIND_VERBS[artifact.kind], (
                f"{artifact.ref} declares {actions} unavailable on "
                f"{artifact.kind}"
            )


def test_benign_catalog_never_offers_a_malicious_distractor():
    from app.services.scenario_generation import get_resources
    from app.services.scenario_generation.planner import plan_candidates

    resources = get_resources()
    for intent in INTENTS:
        catalog = plan_candidates(intent, resources, benign=True, seed="seed")
        assert catalog, f"{intent} has no benign catalog"
        assert all(artifact.benign for artifact in catalog), intent
