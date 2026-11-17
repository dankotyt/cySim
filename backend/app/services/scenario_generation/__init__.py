"""Scenario generation package: rooms, validators, event engine, dedup.

Entry points used by :mod:`app.services.scenario_service`:

* :class:`RoomGenerator` — LLM pipeline with retries and a deterministic
  fallback;
* :class:`EventEngine` — replays an attempt's action log into an outcome;
* :func:`validate_room` — L0-L3 invariants;
* :func:`room_fingerprint` — structural duplicate detection.
"""
from .classifier import (
    Classification,
    IntentClassificationError,
    RuleIntentClassifier,
    build_classifier_prompt,
)
from .dedup import room_fingerprint
from .goals import Goal, GoalSyntaxError, evaluate_goal, parse_goal
from .pipeline import NoArtifactsError, RoomGenerationResult, RoomGenerator
from .registry import (
    Artifact,
    ArtifactRegistry,
    GenerationResources,
    Lesson,
    LessonCatalog,
    get_resources,
    load_resources,
)
from .scoring import AppliedEvent, Evaluation, EventEngine
from .validators import Problem, ValidationResult, validate_room

__all__ = [
    "AppliedEvent",
    "Artifact",
    "ArtifactRegistry",
    "Classification",
    "Evaluation",
    "EventEngine",
    "GenerationResources",
    "Goal",
    "GoalSyntaxError",
    "IntentClassificationError",
    "Lesson",
    "LessonCatalog",
    "NoArtifactsError",
    "Problem",
    "RoomGenerationResult",
    "RoomGenerator",
    "RuleIntentClassifier",
    "ValidationResult",
    "build_classifier_prompt",
    "evaluate_goal",
    "get_resources",
    "load_resources",
    "parse_goal",
    "room_fingerprint",
    "validate_room",
]
