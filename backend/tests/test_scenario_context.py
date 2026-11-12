"""Unit tests for LLM context packaging of security rules."""
from app.models.document import SecurityRule
from app.services.scenario_context import build_scenario_context


def test_build_scenario_context_formats_rules():
    rules = [
        SecurityRule(
            description="Запрещено передавать учётные данные третьим лицам.",
            topic="passwords",
            audience=["general"],
            document_id="doc-1",
        ),
        SecurityRule(
            description="Подозрительные вложения пересылать в СБ.",
            topic="phishing",
            audience=["general"],
            document_id="doc-1",
        ),
    ]
    context = build_scenario_context(rules)

    assert "Правило 1 [passwords]" in context
    assert "Правило 2 [phishing]" in context
    assert "Запрещено передавать учётные данные" in context
    assert "Аудитория: general" in context


def test_build_scenario_context_empty():
    assert build_scenario_context([]) == "Релевантные правила не найдены."
