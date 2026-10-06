"""LLM-based structuring of document chunks into security rules."""
import json
import math
import re

from ..core.logging import get_logger
from ..models.document import Chunk, SecurityRule
from ..utils.embeddings import EmbeddingProvider
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
        embedding_provider: EmbeddingProvider,
        batch_size: int = 5,
        num_ctx: int = 8192,
        dedup_threshold: float = 0.9,
    ) -> None:
        self.llm_provider = llm_provider
        self.embedding_provider = embedding_provider
        self.batch_size = batch_size
        self.dedup_threshold = dedup_threshold
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

    def structure(
        self, chunks: list[Chunk], tenant_id: str, document_id: str
    ) -> list[SecurityRule]:
        """Batch chunks through the LLM and return validated, deduped rules."""
        if not chunks:
            return []

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

        raw_rules: list[dict] = []
        used_topics: list[str] = []
        for batch in batches:
            prompt = self._build_prompt(batch, used_topics)
            raw = self.session_manager.generate(
                prompt, system=self._system_prompt(), anchor=used_topics
            )
            parsed = self._parse(raw)
            valid = self._validate(parsed, batch)
            raw_rules.extend(valid)
            for rule in valid:
                if rule["topic"] not in used_topics:
                    used_topics.append(rule["topic"])

        deduped = self._dedupe(raw_rules)
        logger.info(
            "Extracted %d rules (%d dropped by dedup) for document_id=%s",
            len(deduped),
            len(raw_rules) - len(deduped),
            document_id,
        )
        return [
            SecurityRule(
                title=rule["title"],
                description=rule["description"],
                section=rule["section"],
                topic=rule["topic"],
                linked_docs=rule.get("linked_docs", []),
                document_id=document_id,
            )
            for rule in deduped
        ]

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

    def _validate(self, rules: list[dict], batch: list[Chunk]) -> list[dict]:
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
        if dropped:
            logger.info("Dropped %d rules during validation", dropped)
        return valid

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
        numbers = re.findall(r"\d+", description)
        if any(number not in source_text for number in numbers):
            return False

        return True

    def _dedupe(self, rules: list[dict]) -> list[dict]:
        if not rules:
            return []
        descriptions = [rule["description"] for rule in rules]
        try:
            embeddings = self.embedding_provider.embed_texts(descriptions)
        except Exception as exc:  # noqa: BLE001 - dedup is best-effort
            logger.warning("Embedding dedup unavailable (%s); keeping all rules", exc)
            return rules

        kept: list[dict] = []
        kept_embeddings: list[list[float]] = []
        for rule, embedding in zip(rules, embeddings):
            if any(
                self._cosine(embedding, existing) > self.dedup_threshold
                for existing in kept_embeddings
            ):
                continue
            kept.append(rule)
            kept_embeddings.append(embedding)
        return kept

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
