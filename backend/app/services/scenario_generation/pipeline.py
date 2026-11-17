"""Room generation pipeline: plan -> prompt -> LLM -> L0-L3 -> retry -> fallback.

A rule always yields a room: after ``MAX_ATTEMPTS`` rejected generations the
pipeline falls back to a deterministic room built from the fixture registry, so
a batch run never fails because of one bad model output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import ValidationError

from ...core.intents import INTENTS
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
MAX_DUPLICATE_ATTEMPTS = 2
_ALLOWED_FIELDS = {"v", "title", "brief", "diff", "objs", "goal"}


def _digest(room: Room) -> str:
    """Compact rendering of a rejected room for the retry prompt."""
    objects = "; ".join(
        f"{obj.id}:{obj.kind}:{obj.ref}" for obj in room.objs
    )
    return f"title={room.title!r}; goal={room.goal!r}; objs=[{objects}]"


class TextGenerator(Protocol):
    """Anything that can answer a prompt (an LLM provider or session manager)."""

    async def generate(
        self, prompt: str, *, system: str | None = None
    ) -> str: ...


class NoArtifactsError(ValueError):
    """Raised when the registry has no artifact for the intent/polarity."""


@dataclass(frozen=True)
class RoomGenerationResult:
    """A validated room plus how it was obtained."""

    room: Room
    attempts: int
    source: Literal["llm", "fallback"]
    problems: tuple[str, ...] = ()


class RoomGenerator:
    """Generate a room for one rule and one intent polarity."""

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
        intent: str,
        benign: bool,
        tenant_id: str,
        department: str,
        recent_fingerprints: set[str] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> RoomGenerationResult:
        """Generate and validate a room for ``rule`` as ``intent``."""
        spec = INTENTS.get(intent)
        if spec is None:
            raise NoArtifactsError(f"unknown intent {intent!r}")

        recent = recent_fingerprints or set()
        problems: list[str] = []
        rejected_refs: set[str] = set()
        duplicate_streak = 0
        context = build_scenario_context([rule])
        attempt = 0

        for attempt in range(1, max_attempts + 1):
            seed = f"{tenant_id}:{rule.id}:{intent}:{benign}:{attempt}"
            catalog = plan_candidates(
                intent,
                self._resources,
                benign=benign,
                seed=seed,
                exclude_refs=rejected_refs,
            )
            if not catalog:
                raise NoArtifactsError(
                    f"no artifact with benign={benign} for intent {intent!r}"
                )
            prompt = build_room_prompt(
                context=context,
                spec=spec,
                department=department,
                catalog=catalog,
                benign=benign,
            )
            if problems:
                prompt += (
                    "\n\n## Исправь ошибки предыдущего ответа\n"
                    "Не повторяй отклонённую комнату: измени состав объектов "
                    "и/или формулировку задания.\n"
                    + "\n".join(f"- {problem}" for problem in problems[-8:])
                )

            raw = await self._llm.generate(prompt, system=ROOM_SYSTEM_PROMPT)
            try:
                room = self._parse_room(raw, rule, intent)
            except (ValueError, ValidationError) as exc:
                problems.append(f"L0 json: {exc}")
                logger.warning(
                    "Room attempt %d for rule=%s has invalid JSON: %s",
                    attempt, rule.id, exc,
                )
                continue

            result = validate_room(
                room,
                intent=intent,
                benign=benign,
                resources=self._resources,
            )
            if not result.ok:
                problems.extend(result.lines())
                problems.append(f"Отклонённая комната: {_digest(room)}")
                rejected_refs.update(obj.ref for obj in room.objs)
                logger.warning(
                    "Room attempt %d for rule=%s failed validation: %s",
                    attempt, rule.id, result.summary(),
                )
                continue

            fingerprint = room_fingerprint(room)
            if fingerprint in recent:
                duplicate_streak += 1
                problems.append(
                    "L4 duplicate: такая комната уже есть у тенанта. "
                    f"Не повторяй её: {_digest(room)}"
                )
                rejected_refs.update(obj.ref for obj in room.objs)
                logger.warning(
                    "Room attempt %d for rule=%s is a structural duplicate "
                    "(streak=%d)",
                    attempt, rule.id, duplicate_streak,
                )
                if duplicate_streak >= MAX_DUPLICATE_ATTEMPTS:
                    logger.warning(
                        "Giving up on LLM variety for rule=%s: the catalog is "
                        "too small to produce a new fingerprint",
                        rule.id,
                    )
                    break
                continue

            return RoomGenerationResult(
                room=room, attempts=attempt, source="llm", problems=tuple(problems)
            )

        room = self._fallback(rule, intent, benign, tenant_id, recent)
        logger.warning(
            "Falling back to a deterministic room for rule=%s after %d attempts",
            rule.id, attempt,
        )
        return RoomGenerationResult(
            room=room,
            attempts=attempt,
            source="fallback",
            problems=tuple(problems),
        )

    def _fallback(
        self,
        rule: SecurityRule,
        intent: str,
        benign: bool,
        tenant_id: str,
        recent: set[str],
    ) -> Room:
        """Pick the first deterministic fallback that is not a duplicate."""
        seed = f"{tenant_id}:{rule.id}:{intent}:{benign}:fallback"
        room = fallback_room(
            intent, self._resources, benign=benign, seed=seed
        )
        for offset in range(1, 5):
            if room_fingerprint(room) not in recent:
                break
            room = fallback_room(
                intent,
                self._resources,
                benign=benign,
                seed=seed,
                offset=offset,
            )
        room.topic = rule.topic
        if room_fingerprint(room) in recent:
            logger.warning(
                "Fallback for rule=%s is also a structural duplicate; "
                "the tenant already has every variation of this intent",
                rule.id,
            )
        return room

    @staticmethod
    def _parse_room(raw: str, rule: SecurityRule, intent: str) -> Room:
        """Parse the model output into a room, ignoring unknown fields."""
        data = parse_llm_json_object(raw)
        payload = {
            key: value for key, value in data.items() if key in _ALLOWED_FIELDS
        }
        payload.setdefault("v", ROOM_VERSION)
        if payload["v"] != ROOM_VERSION:
            raise ValueError(f"v must be {ROOM_VERSION}, got {payload['v']!r}")
        payload["topic"] = rule.topic
        payload["intent"] = intent
        return Room.model_validate(payload)
