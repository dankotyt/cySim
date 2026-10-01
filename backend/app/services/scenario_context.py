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
    return (
        f"Правило {index} [{rule.category}]\n"
        f"Название: {rule.title}\n"
        f"Содержание: {rule.description}\n"
        f"Источник: {rule.source} (стр. {rule.page}, score={rule.score:.3f})"
    )


def build_scenario_context(rules: list[SecurityRule]) -> str:
    """Return a prompt-ready text block describing the given rules."""
    if not rules:
        return _NO_RULES_MESSAGE
    return "\n\n".join(_format_rule(index, rule) for index, rule in enumerate(rules, start=1))
