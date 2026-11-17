"""Fixture artifact registry and lesson catalog used by room generation.

Until the web corpus exists (milestone M6) the generator draws objects from a
small hand-written registry that already carries the metadata the corpus will
carry: ``benign`` and per-verb ``risk[]``. The registry is read-only data, not
code — see ``fixtures/artifacts.json``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from ...core.intents import INTENTS
from ...models.scenario import ObjKind, Verb

FIXTURE_BUILD_ID = "fx"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class ArtifactRisk(BaseModel):
    """What a specific action on an artifact does to the room."""

    on: Verb
    level: str = Field(pattern=r"^(soft|hard)$")
    pen: int = Field(ge=0, le=50)
    lesson: str = Field(min_length=1)


class Artifact(BaseModel):
    """A single corpus object with its behaviour metadata."""

    id: str = Field(min_length=1, max_length=64)
    kind: ObjKind
    benign: bool
    intents: list[str] = Field(default_factory=list)
    title: str = Field(min_length=1, max_length=200)
    summary: str = ""
    # Actions that solve this artifact. Empty means "use the intent default";
    # a curated override is required when the intent-level verb is wrong for
    # this particular object (see ADR-0008, amendment 2026-11-17).
    goal_actions: list[Verb] = Field(default_factory=list)
    risk: list[ArtifactRisk] = Field(default_factory=list)
    # Artifact ids reachable from this one; ``via: "<obj>:link:<index>"``
    # addresses this list.
    links: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)

    @property
    def ref(self) -> str:
        """Corpus-style reference: ``<build>:<kind>:<id>``."""
        return f"{FIXTURE_BUILD_ID}:{self.kind}:{self.id}"

    @property
    def key(self) -> str:
        """Build-independent key: ``<kind>:<id>``."""
        return f"{self.kind}:{self.id}"

    def risk_for(self, verb: str) -> ArtifactRisk | None:
        """Return the risk attached to ``verb`` on this artifact, if any."""
        for risk in self.risk:
            if risk.on == verb:
                return risk
        return None

    def goal_actions_for(self, intent: str) -> tuple[str, ...]:
        """Return the actions that satisfy a room built around this artifact.

        The artifact owns the answer key: its ``goal_actions`` override the
        coarse per-intent default. The default keeps legacy fixtures working
        and is only a fallback, never a statement that the intent has one
        universally correct action.
        """
        if self.goal_actions:
            return tuple(self.goal_actions)
        spec = INTENTS.get(intent)
        if spec is None:
            return ()
        return (spec.benign_verb if self.benign else spec.threat_verb,)


class Lesson(BaseModel):
    """A mini-lesson shown to the trainee after a mistake."""

    id: str
    title: str
    text: str


class ArtifactRegistry:
    """Lookup table over fixture artifacts, keyed by ``ref``."""

    def __init__(self, artifacts: list[Artifact]) -> None:
        self._by_ref: dict[str, Artifact] = {}
        self._by_id: dict[str, Artifact] = {}
        for artifact in artifacts:
            if artifact.ref in self._by_ref:
                raise ValueError(f"duplicate artifact ref {artifact.ref!r}")
            if artifact.id in self._by_id:
                raise ValueError(f"duplicate artifact id {artifact.id!r}")
            self._by_ref[artifact.ref] = artifact
            self._by_id[artifact.id] = artifact
        self._artifacts = list(artifacts)

    def get(self, ref: str) -> Artifact | None:
        """Return the artifact with this corpus reference."""
        return self._by_ref.get(ref)

    def get_by_id(self, artifact_id: str) -> Artifact | None:
        """Return the artifact with this build-independent id."""
        return self._by_id.get(artifact_id)

    def all(self) -> list[Artifact]:
        """Return every registered artifact."""
        return list(self._artifacts)

    def for_intent(self, intent: str) -> list[Artifact]:
        """Return artifacts that can depict ``intent``."""
        return [artifact for artifact in self._artifacts if intent in artifact.intents]

    def has_polarity(self, intent: str, benign: bool) -> bool:
        """Return ``True`` when ``intent`` has an artifact of this polarity."""
        return any(
            artifact.benign == benign and intent in artifact.intents
            for artifact in self._artifacts
        )

    def __len__(self) -> int:
        return len(self._artifacts)


class LessonCatalog:
    """Lookup table over mini-lessons."""

    def __init__(self, lessons: list[Lesson]) -> None:
        self._by_id = {lesson.id: lesson for lesson in lessons}

    def get(self, lesson_id: str) -> Lesson | None:
        """Return the lesson with this id."""
        return self._by_id.get(lesson_id)

    def __contains__(self, lesson_id: object) -> bool:
        return lesson_id in self._by_id

    def all(self) -> list[Lesson]:
        """Return every lesson."""
        return list(self._by_id.values())


@dataclass(frozen=True)
class GenerationResources:
    """Everything generation needs to know about the corpus."""

    artifacts: ArtifactRegistry
    lessons: LessonCatalog
    build_id: str = FIXTURE_BUILD_ID


def _read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _items(payload: object, key: str) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get(key, [])
    if not isinstance(payload, list):
        raise ValueError(f"{key} must be a list")
    return payload


def load_resources(directory: Path | None = None) -> GenerationResources:
    """Load artifacts and lessons from ``directory`` (or the bundled fixtures)."""
    directory = directory or FIXTURES_DIR
    artifacts = [
        Artifact.model_validate(item)
        for item in _items(_read_json(directory / "artifacts.json"), "artifacts")
    ]
    lessons = [
        Lesson.model_validate(item)
        for item in _items(_read_json(directory / "lessons.json"), "lessons")
    ]

    by_id = {artifact.id for artifact in artifacts}
    for artifact in artifacts:
        for link in artifact.links:
            if link not in by_id:
                raise ValueError(
                    f"artifact {artifact.id!r} links to unknown artifact {link!r}"
                )

    lesson_ids = {lesson.id for lesson in lessons}
    for artifact in artifacts:
        for intent in artifact.intents:
            if intent not in INTENTS:
                raise ValueError(
                    f"artifact {artifact.id!r} uses unknown intent {intent!r}"
                )
        for risk in artifact.risk:
            if risk.lesson not in lesson_ids:
                raise ValueError(
                    f"artifact {artifact.id!r} references unknown lesson "
                    f"{risk.lesson!r}"
                )

    return GenerationResources(
        artifacts=ArtifactRegistry(artifacts),
        lessons=LessonCatalog(lessons),
    )


@lru_cache(maxsize=1)
def get_resources() -> GenerationResources:
    """Return the bundled fixture resources (loaded once per process)."""
    return load_resources()
