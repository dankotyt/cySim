"""Event engine: turns a trainee's action log into an outcome and a score.

The engine is a pure function of ``(room, artifact registry, events)``, so an
attempt can always be re-evaluated from its log — there is no hidden session
state to drift from the database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ...models.scenario import AttemptEvent, AttemptOutcome, Room, max_points_for
from .goals import Goal, evaluate_goal, parse_goal
from .registry import Artifact, ArtifactRegistry, ArtifactRisk

FALSE_POSITIVE_LESSON = "L_FALSE_POSITIVE"
FALSE_POSITIVE_PEN = 2
BLIND_PENALTY = 2
# Blind means "clicked everything in a burst", not "answered on the first try":
# three actions with at most two seconds between them, without any inspection.
BLIND_BURST_SECONDS = 2.0
BLIND_BURST_EVENTS = 3
# A hard trap ends the room at 1 point, not 0: zero stays reserved for an
# attempt where no lesson/evaluation was produced, so a fatal mistake remains
# distinguishable from missing data.
HARD_FAIL_SCORE = 1


@dataclass(frozen=True)
class AppliedEvent:
    """An event together with the consequence the engine assigned to it."""

    verb: str
    obj: str
    level: str | None = None
    pen: int = 0
    lesson: str | None = None


@dataclass(frozen=True)
class Evaluation:
    """Result of replaying an attempt's events."""

    outcome: AttemptOutcome
    score: int | None
    max_points: int
    goal_met: bool
    blind: bool
    lessons: tuple[str, ...]
    events: tuple[AppliedEvent, ...]


def _false_positive_risk() -> ArtifactRisk:
    """Reporting a legitimate artifact is a soft trap (anti report-all)."""
    return ArtifactRisk(
        on="report",
        level="soft",
        pen=FALSE_POSITIVE_PEN,
        lesson=FALSE_POSITIVE_LESSON,
    )


def _is_burst(times: Sequence[datetime]) -> bool:
    """Return ``True`` when actions arrive as a rapid burst.

    A deliberate first-try answer is not blind. Blind is the pattern of a
    trainee clicking every affordance: at least :data:`BLIND_BURST_EVENTS`
    actions, with at least ``BLIND_BURST_EVENTS - 1`` gaps at most
    :data:`BLIND_BURST_SECONDS`.
    """
    if len(times) < BLIND_BURST_EVENTS:
        return False
    gaps = [
        (current - previous).total_seconds()
        for previous, current in zip(times, times[1:])
    ]
    rapid = sum(1 for gap in gaps if gap <= BLIND_BURST_SECONDS)
    return rapid >= BLIND_BURST_EVENTS - 1


class EventEngine:
    """Evaluate actions against one room."""

    def __init__(self, room: Room, artifacts: ArtifactRegistry) -> None:
        self._room = room
        self._artifacts = artifacts
        self._objects = {obj.id: obj for obj in room.objs}
        self._goal: Goal = parse_goal(room.goal)

    @property
    def max_points(self) -> int:
        """Maximum score available in this room."""
        return max_points_for(self._room.diff)

    def _artifact_for(self, obj_id: str) -> Artifact | None:
        obj = self._objects.get(obj_id)
        if obj is None:
            return None
        return self._artifacts.get(obj.ref)

    def _risk_for(
        self, verb: str, obj_id: str, artifact: Artifact | None
    ) -> ArtifactRisk | None:
        if artifact is None:
            return None
        risk = artifact.risk_for(verb)
        if risk is not None:
            return risk
        if artifact.benign and verb == "report":
            return _false_positive_risk()
        return None

    def evaluate(self, performed: Sequence[AttemptEvent]) -> Evaluation:
        """Replay ``performed`` events and return the resulting state.

        Unknown objects and verbs are neutral and never dead-end a room. Once
        the goal is met or a hard trap fires the room is closed: later events
        are ignored, which is what the client-side lock also enforces.
        """
        max_points = self.max_points
        seen: set[tuple[str, str]] = set()
        times: list[datetime] = []
        applied: list[AppliedEvent] = []
        lessons: list[str] = []
        penalty = 0
        inspected = False
        hard_hit = False
        goal_met = False

        for event in performed:
            if hard_hit or goal_met:
                break
            # Duplicates and unknown objects still count towards the burst:
            # repeatedly clicking the same button is exactly the behaviour
            # the blind penalty is meant to catch.
            times.append(event.at)
            key = (event.verb, event.obj)
            if key in seen:
                continue
            seen.add(key)

            verb, obj_id = event.verb, event.obj
            if verb == "inspect":
                inspected = True

            artifact = self._artifact_for(obj_id)
            risk = self._risk_for(verb, obj_id, artifact)
            if risk is None:
                applied.append(AppliedEvent(verb=verb, obj=obj_id))
            else:
                penalty += risk.pen
                if risk.lesson not in lessons:
                    lessons.append(risk.lesson)
                applied.append(
                    AppliedEvent(
                        verb=verb,
                        obj=obj_id,
                        level=risk.level,
                        pen=risk.pen,
                        lesson=risk.lesson,
                    )
                )
                if risk.level == "hard":
                    hard_hit = True

            if not hard_hit and evaluate_goal(self._goal, seen):
                goal_met = True

        blind = goal_met and not inspected and _is_burst(times)
        score = max_points - penalty - (BLIND_PENALTY if blind else 0)

        if hard_hit:
            outcome: AttemptOutcome = "failed"
            score = HARD_FAIL_SCORE
        elif goal_met:
            outcome = "recovered" if penalty else "safe"
            score = min(max(score, 0), max_points)
        else:
            outcome = "in_progress"
            score = None

        return Evaluation(
            outcome=outcome,
            score=score,
            max_points=max_points,
            goal_met=goal_met,
            blind=blind,
            lessons=tuple(lessons),
            events=tuple(applied),
        )
