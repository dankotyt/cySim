"""Unit tests for LLM context packaging of security rules."""
from app.models.document import SecurityRule
from app.services.scenario_context import build_scenario_context


def test_build_scenario_context_formats_rules():
    rules = [
        SecurityRule(
            title="Не передавать пароли",
            description="Запрещено передавать учётные данные третьим лицам.",
            section="Пароли",
            topic="passwords",
            linked_docs=["Регламент доступа"],
            document_id="doc-1",
        ),
        SecurityRule(
            title="Сообщать о фишинге",
            description="Подозрительные вложения пересылать в СБ.",
            section="Электронная почта",
            topic="phishing",
            linked_docs=[],
            document_id="doc-1",
        ),
    ]
    context = build_scenario_context(rules)

    assert "Правило 1 [passwords]" in context
    assert "Правило 2 [phishing]" in context
    assert "Не передавать пароли" in context
    assert "Раздел: Пароли" in context
    assert "Связанные документы: Регламент доступа" in context


def test_build_scenario_context_empty():
    assert build_scenario_context([]) == "Релевантные правила не найдены."
