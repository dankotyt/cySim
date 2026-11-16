"""Static invariants for a generated room (L0-L3).

Every room passes through these checks before it is stored; failures are fed
back to the model as retry instructions. The levels mirror ADR-0008:

* **L0** — shape: version, counts, goal parses.
* **L1** — references: artifacts exist, verbs fit the object kind, ``via``
  resolves, lessons exist.
* **L2** — grounding: traps of the room belong to the rule's topic.
* **L3** — solvability: the goal is reachable, not satisfied from the start,
  needs at least one report of a malicious object, and no trap blocks it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...models.scenario import (
    MAX_OBJECTS,
    MIN_OBJECTS,
    ROOM_VERSION,
    Room,
    RoomObject,
)
from .goals import GoalSyntaxError, evaluate_goal, parse_goal
from .registry import Artifact, GenerationResources

KIND_VERBS: dict[str, frozenset[str]] = {
    "email": frozenset(
        {"open", "inspect", "click", "download", "reply", "report", "dismiss"}
    ),
    "site": frozenset(
        {"open", "inspect", "click", "download", "submit", "report", "dismiss"}
    ),
    "pdf": frozenset({"open", "inspect", "download", "report", "dismiss"}),
    "usb": frozenset({"open", "inspect", "download", "connect", "report", "dismiss"}),
    "call": frozenset({"answer", "inspect", "speak", "report", "dismiss"}),
}

_VIA_RE = re.compile(r"^(?P<source>[A-Za-z0-9_-]+):link:(?P<index>\d+)$")


@dataclass(frozen=True)
class Problem:
    """A single invariant violation."""

    level: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.level} {self.code}: {self.message}"


@dataclass
class ValidationResult:
    """Collected problems; empty means the room is valid."""

    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether the room passed all levels."""
        return not self.problems

    def summary(self, limit: int = 8) -> str:
        """Render problems for a retry prompt."""
        shown = self.problems[:limit]
        return "; ".join(str(problem) for problem in shown)

    def lines(self, limit: int = 8) -> list[str]:
        """Render problems one per line for a retry prompt."""
        return [str(problem) for problem in self.problems[:limit]]


def _artifact_map(
    room: Room, resources: GenerationResources
) -> tuple[dict[str, Artifact], list[Problem]]:
    """Resolve every object to its artifact, reporting L1 failures."""
    resolved: dict[str, Artifact] = {}
    problems: list[Problem] = []
    for obj in room.objs:
        artifact = resources.artifacts.get(obj.ref)
        if artifact is None:
            problems.append(
                Problem("L1", "unknown_ref", f"ref {obj.ref!r} is not in the corpus")
            )
            continue
        if artifact.kind != obj.kind:
            problems.append(
                Problem(
                    "L1",
                    "kind_mismatch",
                    f"object {obj.id!r} is {obj.kind!r} but {obj.ref!r} is "
                    f"{artifact.kind!r}",
                )
            )
            continue
        resolved[obj.id] = artifact
    return resolved, problems


def _check_duplicate_refs(room: Room) -> list[Problem]:
    refs = [obj.ref for obj in room.objs]
    if len(refs) != len(set(refs)):
        return [Problem("L1", "duplicate_ref", "the same artifact is used twice")]
    return []


def _check_via(
    room: Room, resolved: dict[str, Artifact]
) -> list[Problem]:
    """Validate ``via`` links and reject cycles in the navigation graph."""
    problems: list[Problem] = []
    objects = {obj.id: obj for obj in room.objs}
    edges: dict[str, str] = {}

    for obj in room.objs:
        if obj.via is None:
            continue
        match = _VIA_RE.match(obj.via)
        if match is None:
            problems.append(
                Problem(
                    "L1",
                    "bad_via",
                    f"object {obj.id!r} has malformed via {obj.via!r}; expected "
                    f"'<obj>:link:<index>'",
                )
            )
            continue
        source_id = match.group("source")
        index = int(match.group("index"))
        source = objects.get(source_id)
        if source is None:
            problems.append(
                Problem(
                    "L1",
                    "via_unknown_source",
                    f"object {obj.id!r} is reached from unknown object {source_id!r}",
                )
            )
            continue
        edges[obj.id] = source_id
        source_artifact = resolved.get(source_id)
        target_artifact = resolved.get(obj.id)
        if source_artifact is None or target_artifact is None:
            continue
        if index >= len(source_artifact.links):
            problems.append(
                Problem(
                    "L1",
                    "via_bad_index",
                    f"object {source_id!r} has no link at index {index}",
                )
            )
            continue
        if source_artifact.links[index] != target_artifact.id:
            problems.append(
                Problem(
                    "L1",
                    "via_mismatch",
                    f"{source_id!r} link {index} points to "
                    f"{source_artifact.links[index]!r}, not {target_artifact.id!r}",
                )
            )

    if _has_cycle(edges):
        problems.append(Problem("L1", "via_cycle", "the via graph contains a cycle"))
    return problems


def _has_cycle(edges: dict[str, str]) -> bool:
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        source = edges.get(node)
        if source is not None and visit(source):
            return True
        state[node] = 2
        return False

    return any(visit(node) for node in edges)


def _check_goal_literals(
    goal, objects: dict[str, RoomObject]
) -> list[Problem]:
    """Check that goal verbs address existing objects with allowed verbs."""
    problems: list[Problem] = []
    for verb, obj_id in sorted(goal.literals):
        obj = objects.get(obj_id)
        if obj is None:
            problems.append(
                Problem("L1", "goal_unknown_obj", f"goal refers to unknown object {obj_id!r}")
            )
            continue
        if verb not in KIND_VERBS[obj.kind]:
            problems.append(
                Problem(
                    "L1",
                    "goal_bad_verb",
                    f"verb {verb!r} is not available on {obj.kind!r} object {obj_id!r}",
                )
            )
    return problems


def _check_lessons(
    resolved: dict[str, Artifact], resources: GenerationResources
) -> list[Problem]:
    problems: list[Problem] = []
    seen: set[str] = set()
    for artifact in resolved.values():
        for risk in artifact.risk:
            if risk.lesson in seen:
                continue
            seen.add(risk.lesson)
            if risk.lesson not in resources.lessons:
                problems.append(
                    Problem(
                        "L1",
                        "unknown_lesson",
                        f"artifact {artifact.id!r} uses unknown lesson "
                        f"{risk.lesson!r}",
                    )
                )
    return problems


def _check_grounding(
    resolved: dict[str, Artifact], rule_topic: str
) -> list[Problem]:
    problems: list[Problem] = []
    grounded = False
    for artifact in resolved.values():
        if rule_topic in artifact.topics:
            grounded = True
        if any(risk.level == "hard" for risk in artifact.risk):
            if rule_topic not in artifact.topics:
                problems.append(
                    Problem(
                        "L2",
                        "ungrounded_trap",
                        f"artifact {artifact.id!r} has a hard trap but is not "
                        f"tagged with rule topic {rule_topic!r}",
                    )
                )
    if resolved and not grounded:
        problems.append(
            Problem(
                "L2",
                "ungrounded_room",
                f"no object is tagged with rule topic {rule_topic!r}",
            )
        )
    return problems


def _check_solvability(goal, resolved: dict[str, Artifact]) -> list[Problem]:
    problems: list[Problem] = []

    if evaluate_goal(goal, set()):
        problems.append(
            Problem("L3", "goal_trivially_true", "the goal holds before any action")
        )

    reports_on_malicious = 0
    for verb, obj_id in sorted(goal.literals):
        artifact = resolved.get(obj_id)
        if artifact is None:
            continue
        if verb == "report" and artifact.benign:
            problems.append(
                Problem(
                    "L3",
                    "report_on_benign",
                    f"goal requires report({obj_id}) on a legitimate object "
                    f"(false-positive training)",
                )
            )
        if verb == "report" and not artifact.benign:
            reports_on_malicious += 1

    if reports_on_malicious == 0:
        problems.append(
            Problem(
                "L3",
                "no_report_of_threat",
                "the goal must require reporting at least one malicious object",
            )
        )

    for verb, obj_id in sorted(goal.positive):
        artifact = resolved.get(obj_id)
        if artifact is None:
            continue
        risk = artifact.risk_for(verb)
        if risk is not None and risk.level == "hard":
            problems.append(
                Problem(
                    "L3",
                    "goal_blocked_by_trap",
                    f"the goal needs {verb}({obj_id}), which is a hard trap",
                )
            )

    for obj_id, artifact in resolved.items():
        hard = [risk for risk in artifact.risk if risk.level == "hard"]
        if artifact.benign and hard:
            problems.append(
                Problem(
                    "L3",
                    "benign_with_hard",
                    f"legitimate artifact {artifact.id!r} has a hard trap",
                )
            )
        if not artifact.benign and not hard:
            problems.append(
                Problem(
                    "L3",
                    "malicious_without_hard",
                    f"malicious artifact {artifact.id!r} has no hard trap",
                )
            )
    return problems


def validate_room(
    room: Room, *, rule_topic: str, resources: GenerationResources
) -> ValidationResult:
    """Run L0-L3 checks over ``room`` and return every violation."""
    result = ValidationResult()

    if room.v != ROOM_VERSION:
        result.problems.append(
            Problem("L0", "unsupported_version", f"v must be {ROOM_VERSION}, got {room.v}")
        )
    if not MIN_OBJECTS <= len(room.objs) <= MAX_OBJECTS:
        result.problems.append(
            Problem(
                "L0",
                "object_count",
                f"a room needs {MIN_OBJECTS}-{MAX_OBJECTS} objects, got {len(room.objs)}",
            )
        )

    try:
        goal = parse_goal(room.goal)
    except GoalSyntaxError as exc:
        result.problems.append(Problem("L0", "bad_goal", str(exc)))
        return result

    resolved, resolve_problems = _artifact_map(room, resources)
    result.problems.extend(resolve_problems)
    result.problems.extend(_check_duplicate_refs(room))
    result.problems.extend(_check_via(room, resolved))

    objects = {obj.id: obj for obj in room.objs}
    result.problems.extend(_check_goal_literals(goal, objects))
    result.problems.extend(_check_lessons(resolved, resources))
    result.problems.extend(_check_grounding(resolved, rule_topic))
    result.problems.extend(_check_solvability(goal, resolved))
    return result
