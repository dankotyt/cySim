"""Package extracted security rules into LLM-ready context.

This is the public seam between the RAG pipeline and the scenario-generation
module: callers pass the typed :class:`SecurityRule` list returned by
``DocumentService.extract_rules`` and receive a deterministic, prompt-ready
text block that can be embedded directly into an LLM prompt.
"""
from ..models.document import SecurityRule

_NO_RULES_MESSAGE = "Релевантные правила не найдены."


def _format_rule(index: int, rule: SecurityRule) -> str:
    """Format a single rule as a numbered, structured block."""
    linked = ", ".join(rule.linked_docs) if rule.linked_docs else "—"
    return (
        f"Правило {index} [{rule.topic}]\n"
        f"Название: {rule.title}\n"
        f"Раздел: {rule.section or '—'}\n"
        f"Содержание: {rule.description}\n"
        f"Связанные документы: {linked}"
    )


def build_scenario_context(rules: list[SecurityRule]) -> str:
    """Return a prompt-ready text block describing the given rules."""
    if not rules:
        return _NO_RULES_MESSAGE
    return "\n\n".join(_format_rule(index, rule) for index, rule in enumerate(rules, start=1))
