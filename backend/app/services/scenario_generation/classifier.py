"""Classify a security rule into a scenario intent and a corrected topic.

The rule's own ``topic`` comes from the LoRA extractor and can be wrong (a
screen-lock rule was labelled ``passwords``). The intent is resolved from the
rule text against the fixed catalog in :mod:`app.core.intents`, and the same
step re-labels the topic from :data:`ALLOWED_TOPICS` so cross-tenant analytics
stay meaningful.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...core.intents import (
    INTENTS,
    NOT_REPRESENTABLE,
    get_intent,
    intent_catalog_text,
)
from ...core.topics import ALLOWED_TOPICS
from ...models.document import SecurityRule
from ...utils.llm_json import parse_llm_json_object

CLASSIFIER_SYSTEM_PROMPT = """\
/no_think
Ты — методист по информационной безопасности. Ты определяешь, какую учебную
ситуацию можно разыграть по правилу из политики компании, и уточняешь тему.

Ответ — строго один JSON-объект:
{"intent": "<id>", "topic": "<тема>"}. Никакого markdown.

intent — только идентификатор из списка интентов (или "not_representable").
topic — только значение из списка тем.
Это разные поля: название темы в intent — ошибка, идентификатор интента в
topic — тоже ошибка.
Если правило описывает процесс или роль (кто утверждает документ, как ведётся
журнал, сроки хранения), а не действие сотрудника, верни
{"intent": "not_representable", "topic": "<тема>"}.
"""

CLASSIFIER_ATTEMPTS = 2


class IntentClassificationError(ValueError):
    """Raised when the classifier output cannot be used.

    ``reason`` separates a model that returned a topic instead of an intent
    (``invalid_intent``) from malformed JSON (``invalid_json``), so the batch
    report can distinguish them.
    """

    def __init__(self, message: str, *, reason: str = "classification_failed"):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Classification:
    """Resolved intent plus an optional corrected topic."""

    intent: str
    topic: str | None = None


class TextGenerator(Protocol):
    """Anything that can answer a prompt."""

    async def generate(
        self, prompt: str, *, system: str | None = None
    ) -> str: ...


def build_classifier_prompt(rule: SecurityRule) -> str:
    """Assemble the classification prompt for one rule."""
    return f"""\
Правило: {rule.description}

Тема, определённая извлекателем (черновик, может быть неточной; не используй
её как intent): {rule.topic}

Допустимые темы (только для поля topic):
{', '.join(ALLOWED_TOPICS)}

Доступные интенты (только для поля intent):
{intent_catalog_text()}

Верни JSON {{"intent": "...", "topic": "..."}}."""


class RuleIntentClassifier:
    """Map a rule to an intent and correct its topic."""

    def __init__(self, llm: TextGenerator) -> None:
        self._llm = llm

    async def classify(self, rule: SecurityRule) -> Classification:
        """Return the classification or raise :class:`IntentClassificationError`.

        A model that confuses a topic (``access_control``) with an intent gets
        one corrective retry; only after that the rule is considered failed.
        """
        prompt = build_classifier_prompt(rule)
        last_error = "no response"
        reason = "classification_failed"

        for _attempt in range(1, CLASSIFIER_ATTEMPTS + 1):
            raw = await self._llm.generate(
                prompt, system=CLASSIFIER_SYSTEM_PROMPT
            )
            try:
                data = parse_llm_json_object(raw)
            except ValueError as exc:
                last_error = f"invalid JSON: {exc}"
                reason = "invalid_json"
                prompt = (
                    build_classifier_prompt(rule)
                    + "\n\nПредыдущий ответ не был JSON. Верни только "
                    '{"intent": "...", "topic": "..."}.'
                )
                continue

            intent = str(data.get("intent", "")).strip()
            topic = str(data.get("topic", "")).strip()
            corrected = topic if topic in ALLOWED_TOPICS else None

            if intent == NOT_REPRESENTABLE:
                return Classification(intent=NOT_REPRESENTABLE, topic=corrected)
            if get_intent(intent) is not None:
                return Classification(intent=intent, topic=corrected)

            last_error = f"unknown intent {intent!r}"
            reason = "invalid_intent"
            prompt = (
                build_classifier_prompt(rule)
                + f"\n\nОшибка: {intent!r} не входит в список интентов. intent "
                "выбирается только из списка интентов, тема — отдельное поле "
                "topic. Выбери ровно один идентификатор из списка: "
                f"{', '.join(INTENTS)}."
            )

        raise IntentClassificationError(
            f"classifier failed for rule {rule.id}: {last_error}",
            reason=reason,
        )
