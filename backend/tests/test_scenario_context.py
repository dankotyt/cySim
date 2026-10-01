"""Unit tests for LLM context packaging of security rules."""
from app.models.document import SecurityRule
from app.services.scenario_context import build_scenario_context


def test_build_scenario_context_formats_rules():
    rules = [
        SecurityRule(
            title="Не передавать пароли",
            description="Запрещено передавать учётные данные третьим лицам.",
            category="passwords",
            source="policy.txt",
            page=1,
            score=0.9,
        ),
        SecurityRule(
            title="Сообщать о фишинге",
            description="Подозрительные вложения пересылать в СБ.",
            category="phishing",
            source="policy.txt",
            page=2,
            score=0.8,
        ),
    ]
    context = build_scenario_context(rules)

    assert "Правило 1 [passwords]" in context
    assert "Правило 2 [phishing]" in context
    assert "Не передавать пароли" in context
    assert "policy.txt (стр. 1" in context
    assert "score=0.900" in context


def test_build_scenario_context_empty():
    assert build_scenario_context([]) == "Релевантные правила не найдены."
