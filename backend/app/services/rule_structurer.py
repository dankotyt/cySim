"""LLM-based structuring of document chunks into security rules."""
import json
import re
import time
from dataclasses import dataclass, field

from ..core.logging import get_logger
from ..models.document import Chunk, SecurityRule
from .llm_provider import LLMProvider
from .session_manager import SessionManager

logger = get_logger(__name__)

# Controlled topic vocabulary. The LLM must pick exactly one of these; anything
# that does not fit is mapped to "other". The first eight values double as the
# scenario-generation attack types (see ``AttackType`` in models/scenario.py).
ALLOWED_TOPICS: tuple[str, ...] = (
    "phishing",
    "vishing",
    "baiting",
    "pretexting",
    "tailgating",
    "quid_pro_quo",
    "social_media_osint",
    "usb_drop",
    "passwords",
    "physical_security",
    "data_handling",
    "remote_work",
    "insider_threat",
    "supply_chain",
    "leaked_credentials",
    "access_control",
    "incidents",
    "other",
)

_SYSTEM_PROMPT = """\
/no_think
Ты — анализатор политик информационной безопасности компании.
Извлеки из фрагментов документа структурированные правила.

Отвечай ТОЛЬКО валидным JSON-объектом без markdown и пояснений в формате:
{{"rules": [{{"title": "...", "description": "...", "section": "...", "topic": "...", "linked_docs": ["..."]}}]}}

Требования:
1. Каждое отдельное правило — отдельный элемент массива rules. Разбивай фрагмент на отдельные правила, не объединяй их.
2. description — дословная цитата из фрагмента (подстрока исходного текста). Не перефразируй.
3. section — название раздела документа, как оно написано в тексте; если раздела нет — пустая строка.
4. topic — ОБЯЗАТЕЛЬНО одно значение из списка ALLOWED_TOPICS ниже. Не придумывай новые значения.
5. linked_docs — только внутренние документы компании (регламенты, инструкции, политики), на которые ссылается правило. Внешние (ФЗ, ГОСТ, ISO, NIST) игнорируй.
6. Сохраняй все числа точно как в тексте («12 символов», «90 дней» — не меняй).
7. Не выдумывай факты: используй только информацию из фрагмента.

ALLOWED_TOPICS: {topics}
"""


@dataclass
class StructureResult:
    """Outcome of a structuring run, including per-batch diagnostics."""

    rules: list[SecurityRule] = field(default_factory=list)
    failed_batches: list[int] = field(default_factory=list)
    dropped_by_validation: int = 0
    dropped_by_dedup: int = 0


def _normalize(text: str) -> str:
    """Collapse all whitespace so substrings can be compared reliably."""
    return " ".join(text.split())


def _parse_json(raw: str) -> dict:
    """Parse an LLM response, tolerating markdown fences and stray text."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM output must be a JSON object")
    return parsed


class RuleStructurer:
    """Turn document chunks into validated, deduplicated :class:`SecurityRule` objects."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        batch_size: int = 5,
        num_ctx: int = 8192,
    ) -> None:
        self.llm_provider = llm_provider
        self.batch_size = batch_size
        self.session_manager = SessionManager(llm_provider, num_ctx)

    def _system_prompt(self) -> str:
        return _SYSTEM_PROMPT.format(topics=", ".join(ALLOWED_TOPICS))

    def _build_prompt(self, batch: list[Chunk], used_topics: list[str]) -> str:
        fragments = "\n\n".join(
            f"--- ФРАГМЕНТ {index + 1} ---\n{chunk.text}"
            for index, chunk in enumerate(batch)
        )
        used = ", ".join(used_topics) if used_topics else "(нет)"
        return (
            f"Уже использованные topic: {used}\n\n"
            f"Фрагменты документа:\n{fragments}\n\n"
            f"Извлеки правила и верни JSON в указанном формате."
        )

    async def structure(
        self, chunks: list[Chunk], tenant_id: str, document_id: str
    ) -> StructureResult:
        """Batch chunks through the LLM and return validated, deduped rules."""
        if not chunks:
            return StructureResult()

        batches = [
            chunks[index : index + self.batch_size]
            for index in range(0, len(chunks), self.batch_size)
        ]
        logger.info(
            "Structuring %d chunks in %d batches (document_id=%s)",
            len(chunks),
            len(batches),
            document_id,
        )

        started_total = time.perf_counter()
        raw_rules: list[dict] = []
        used_topics: list[str] = []
        failed_batches: list[int] = []
        dropped_by_validation = 0

        for batch_index, batch in enumerate(batches):
            batch_started = time.perf_counter()
            try:
                prompt = self._build_prompt(batch, used_topics)
                raw = await self.session_manager.generate(
                    prompt, system=self._system_prompt(), anchor=used_topics
                )
                parsed = self._parse(raw)
                valid, dropped = self._validate(parsed, batch)
                dropped_by_validation += dropped
                raw_rules.extend(valid)
                for rule in valid:
                    if rule["topic"] not in used_topics:
                        used_topics.append(rule["topic"])
            except Exception as exc:  # noqa: BLE001 - one bad batch must not abort the run
                failed_batches.append(batch_index)
                logger.error(
                    "Structuring batch %d failed: %s", batch_index, exc
                )
            finally:
                logger.info(
                    "Batch %d/%d took %.2fs",
                    batch_index + 1,
                    len(batches),
                    time.perf_counter() - batch_started,
                )

        deduped, dropped_by_dedup = self._dedupe(raw_rules)
        logger.info(
            "Structuring finished in %.2fs: %d rules (%d dropped by dedup) "
            "for document_id=%s",
            time.perf_counter() - started_total,
            len(deduped),
            dropped_by_dedup,
            document_id,
        )
        return StructureResult(
            rules=[
                SecurityRule(
                    title=rule["title"],
                    description=rule["description"],
                    section=rule["section"],
                    topic=rule["topic"],
                    linked_docs=rule.get("linked_docs", []),
                    document_id=document_id,
                )
                for rule in deduped
            ],
            failed_batches=failed_batches,
            dropped_by_validation=dropped_by_validation,
            dropped_by_dedup=dropped_by_dedup,
        )

    @staticmethod
    def _parse(raw: str) -> list[dict]:
        try:
            data = _parse_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse LLM rule response: %s", exc)
            return []
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            return []
        return [rule for rule in rules if isinstance(rule, dict)]

    def _validate(self, rules: list[dict], batch: list[Chunk]) -> tuple[list[dict], int]:
        valid: list[dict] = []
        dropped = 0
        for raw in rules:
            if self._is_valid(raw, batch):
                valid.append(
                    {
                        "title": str(raw.get("title", "")).strip(),
                        "description": str(raw.get("description", "")).strip(),
                        "section": str(raw.get("section", "")).strip(),
                        "topic": str(raw.get("topic", "")).strip(),
                        "linked_docs": [
                            str(ref).strip()
                            for ref in raw.get("linked_docs", [])
                            if str(ref).strip()
                        ],
                    }
                )
            else:
                dropped += 1
        return valid, dropped

    def _is_valid(self, raw: dict, batch: list[Chunk]) -> bool:
        topic = raw.get("topic")
        if not isinstance(topic, str) or topic not in ALLOWED_TOPICS:
            return False

        description = raw.get("description")
        if not isinstance(description, str) or not description.strip():
            return False

        # Anti-hallucination: description must be a substring of some chunk.
        normalized = _normalize(description)
        source_text = None
        for chunk in batch:
            if normalized in _normalize(chunk.text):
                source_text = chunk.text
                break
        if source_text is None:
            return False

        # Every number in the description must be present in the source chunk.
        # Compare token sets so "12" is not considered present inside "123".
        description_numbers = set(re.findall(r"\b\d+\b", description))
        source_numbers = set(re.findall(r"\b\d+\b", source_text))
        if not description_numbers.issubset(source_numbers):
            return False

        return True

    def _dedupe(self, rules: list[dict]) -> tuple[list[dict], int]:
        """Drop rules whose ``(normalized description, section)`` key repeats."""
        kept: list[dict] = []
        seen: set[tuple[str, str]] = set()
        dropped = 0
        for rule in rules:
            key = (_normalize(rule["description"]), rule["section"])
            if key in seen:
                dropped += 1
                logger.info(
                    "Dropped duplicate rule: %s", rule["description"][:80]
                )
                continue
            seen.add(key)
            kept.append(rule)
        return kept, dropped
