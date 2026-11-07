"""LoRARuleStructurer — extract rules from chunks using a local LoRA adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...core.logging import get_logger
from ...models.document import Chunk, SecurityRule
from ..llm_provider import LLMProvider
from .filters import (
    _is_employee_rule, _is_junk_rule, _normalize,
    _normalize_for_match, _fuzzy_in_chunk
)
from .prompts import _SYSTEM_PROMPT, _build_user_prompt
from .vocab import VALID_TOPICS, _RULE_RE, _validate_audience


logger = get_logger(__name__)


@dataclass
class StructureResult:
    rules: list[SecurityRule] = field(default_factory=list)
    failed_chunks: list[int] = field(default_factory=list)
    dropped_by_validation: int = 0
    dropped_by_filter: int = 0
    dropped_by_dedup: int = 0


class LoRARuleStructurer:
    """Extract rules from chunks using a local LoRA adapter.

    One chunk → one inference call (no batching: the training prompt is
    per-chunk, and 4-bit 7B inference is expensive). Per-chunk failures are
    isolated; a bad chunk does not abort the run.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        strict: bool = False,
    ) -> None:
        self.llm_provider = llm_provider
        self.strict = strict

    async def structure(
        self,
        chunks: list[Chunk],
        tenant_id: str,
        document_id: str,
    ) -> StructureResult:
        """Batch chunks through the LoRA model and return validated rules."""
        if not chunks:
            return StructureResult()

        result = StructureResult()
        seen: set[tuple[str, str]] = set()

        for index, chunk in enumerate(chunks):
            try:
                raw = await self.llm_provider.generate(
                    _build_user_prompt(chunk.text),
                    system=_SYSTEM_PROMPT,
                )
            except Exception as exc:  # noqa: BLE001 — one bad chunk must not abort
                result.failed_chunks.append(index)
                logger.error(
                    "LoRA inference failed for chunk %d: %s", index, exc
                )
                continue

            parsed, dropped, dropped_filter = self._parse_rules(
                raw, chunk.text, document_id
            )
            result.dropped_by_validation += dropped
            result.dropped_by_filter += dropped_filter

            for rule in parsed:
                key = (_normalize(rule.description), rule.topic)
                if key in seen:
                    result.dropped_by_dedup += 1
                    continue
                seen.add(key)
                result.rules.append(rule)

            logger.info(
                "Chunk %d/%d: %d rules extracted",
                index + 1,
                len(chunks),
                len(parsed),
            )

        logger.info(
            "LoRA structuring done: %d rules, failed_chunks=%d, "
            "dropped(validation=%d, filter=%d, dedup=%d) for document_id=%s",
            len(result.rules),
            len(result.failed_chunks),
            result.dropped_by_validation,
            result.dropped_by_filter,
            result.dropped_by_dedup,
            document_id,
        )
        return result

    def _parse_rules(
            self, raw: str, chunk_text: str, document_id: str
    ) -> tuple[list[SecurityRule], int, int]:
        """Parse one model response into validated SecurityRule objects."""
        rules: list[SecurityRule] = []
        dropped = 0
        dropped_filter = 0

        chunk_norm = _normalize_for_match(chunk_text)
        seen_texts: set[str] = set()

        for raw_line in raw.split("\n"):
            line = raw_line.strip()
            if not line or line.startswith("```"):
                continue
            line = re.sub(r"^[-•*]\s*", "", line)
            line = re.sub(r"^\d+[.)]\s*", "", line)

            match = _RULE_RE.match(line)
            if not match:
                dropped += 1
                continue

            audience_str = match.group(1).strip()
            topic = match.group(2)
            text = match.group(3).strip()

            if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
                text = text[1:-1].strip()

            if not _validate_audience(audience_str):
                dropped += 1
                continue
            if topic not in VALID_TOPICS:
                dropped += 1
                continue
            if len(text) < 20:
                dropped += 1
                continue
            if _is_junk_rule(text):
                dropped += 1
                dropped_filter += 1
                continue
            if self.strict and not _is_employee_rule(text):
                dropped += 1
                continue

            text_key = text[:120].lower().strip()
            if text_key in seen_texts:
                dropped += 1
                continue

            if not _fuzzy_in_chunk(text, chunk_norm):
                dropped += 1
                continue

            seen_texts.add(text_key)

            audience = [
                part.strip()
                for part in audience_str.split(",")
                if part.strip()
            ]

            rules.append(
                SecurityRule(
                    description=text,
                    topic=topic,
                    audience=audience,
                    document_id=document_id,
                )
            )

        return rules, dropped, dropped_filter