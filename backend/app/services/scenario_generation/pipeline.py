"""Room generation pipeline: plan -> prompt -> LLM -> L0-L3 -> retry -> fallback.

A rule always yields a room: after ``MAX_ATTEMPTS`` rejected generations the
pipeline falls back to a deterministic room built from the fixture registry, so
a batch run never fails because of one bad model output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import ValidationError

from ...core.logging import get_logger
from ...models.document import SecurityRule
from ...models.scenario import ROOM_VERSION, Room
from ...utils.llm_json import parse_llm_json_object
from ..scenario_context import build_scenario_context
from .dedup import room_fingerprint
from .planner import fallback_room, plan_candidates
from .prompts import ROOM_SYSTEM_PROMPT, build_room_prompt
from .registry import GenerationResources, get_resources
from .validators import validate_room

logger = get_logger(__name__)

MAX_ATTEMPTS = 3
_ALLOWED_FIELDS = {"v", "title", "brief", "diff", "objs", "goal"}


class TextGenerator(Protocol):
    """Anything that can answer a prompt (an LLM provider or session manager)."""

    async def generate(
        self, prompt: str, *, system: str | None = None
    ) -> str: ...


@dataclass(frozen=True)
class RoomGenerationResult:
    """A validated room plus how it was obtained."""

    room: Room
    attempts: int
    source: Literal["llm", "fallback"]
    problems: tuple[str, ...] = ()


class RoomGenerator:
    """Generate a room for one rule, retrying on invalid or duplicate output."""

    def __init__(
        self,
        llm_provider: TextGenerator,
        resources: GenerationResources | None = None,
    ) -> None:
        self._llm = llm_provider
        self._resources = resources or get_resources()

    async def generate(
        self,
        *,
        rule: SecurityRule,
        tenant_id: str,
        department: str,
        recent_fingerprints: set[str] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> RoomGenerationResult:
        """Generate and validate a room for ``rule``."""
        recent = recent_fingerprints or set()
        problems: list[str] = []
        context = build_scenario_context([rule])

        for attempt in range(1, max_attempts + 1):
            seed = f"{tenant_id}:{rule.id}:{attempt}"
            catalog = plan_candidates(rule.topic, self._resources, seed=seed)
            prompt = build_room_prompt(
                context=context,
                topic=rule.topic,
                department=department,
                catalog=catalog,
            )
            if problems:
                prompt += (
                    "\n\n## Исправь ошибки предыдущего ответа\n"
                    + "\n".join(f"- {problem}" for problem in problems[-8:])
                )

            raw = await self._llm.generate(prompt, system=ROOM_SYSTEM_PROMPT)
            try:
                room = self._parse_room(raw, rule)
            except (ValueError, ValidationError) as exc:
                problems.append(f"L0 json: {exc}")
                logger.warning(
                    "Room attempt %d for rule=%s has invalid JSON: %s",
                    attempt, rule.id, exc,
                )
                continue

            result = validate_room(
                room, rule_topic=rule.topic, resources=self._resources
            )
            if not result.ok:
                problems.extend(result.lines())
                logger.warning(
                    "Room attempt %d for rule=%s failed validation: %s",
                    attempt, rule.id, result.summary(),
                )
                continue

            fingerprint = room_fingerprint(room)
            if fingerprint in recent:
                problems.append(
                    "L4 duplicate: комната структурно совпадает с уже "
                    "сгенерированной; выбери другие объекты или другую цель"
                )
                logger.warning(
                    "Room attempt %d for rule=%s is a structural duplicate",
                    attempt, rule.id,
                )
                continue

            return RoomGenerationResult(
                room=room, attempts=attempt, source="llm", problems=tuple(problems)
            )

        room = self._fallback(rule, tenant_id, recent)
        logger.warning(
            "Falling back to a deterministic room for rule=%s after %d attempts",
            rule.id, max_attempts,
        )
        return RoomGenerationResult(
            room=room,
            attempts=max_attempts,
            source="fallback",
            problems=tuple(problems),
        )

    def _fallback(
        self, rule: SecurityRule, tenant_id: str, recent: set[str]
    ) -> Room:
        """Pick the first deterministic fallback that is not a duplicate."""
        seed = f"{tenant_id}:{rule.id}:fallback"
        room = fallback_room(rule.topic, self._resources, seed=seed)
        for offset in range(1, 5):
            if room_fingerprint(room) not in recent:
                break
            room = fallback_room(
                rule.topic, self._resources, seed=seed, offset=offset
            )
        return room

    @staticmethod
    def _parse_room(raw: str, rule: SecurityRule) -> Room:
        """Parse the model output into a room, ignoring unknown fields."""
        data = parse_llm_json_object(raw)
        payload = {
            key: value for key, value in data.items() if key in _ALLOWED_FIELDS
        }
        payload.setdefault("v", ROOM_VERSION)
        if payload["v"] != ROOM_VERSION:
            raise ValueError(
                f"v must be {ROOM_VERSION}, got {payload['v']!r}"
            )
        payload["topic"] = rule.topic
        return Room.model_validate(payload)
