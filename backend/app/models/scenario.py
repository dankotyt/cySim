"""Pydantic models for scenario generation (room contract v1).

The scenario is a *room*: a set of objects, a goal predicate and a short brief,
with no enumerated steps. Behaviour (what breaks the room) lives in the corpus
artifact metadata, not in the scenario itself — see
``docs/adr/0008-room-contract-v1.md``.
"""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..core.config import DEFAULT_EMPLOYEE_ID, DEFAULT_TENANT_ID

# Fixed verb vocabulary: the UI renders affordances per object kind, so the
# generator cannot invent an action the interface does not offer.
Verb = Literal[
    "open",
    "inspect",
    "click",
    "download",
    "submit",
    "reply",
    "connect",
    "answer",
    "speak",
    "report",
    "dismiss",
    # Physical-security affordances (workstation, desk, door, badge).
    "lock",
    "leave",
    "shred",
    "scan",
    "escort",
    "wear",
    "share",
    "return",
]

ObjKind = Literal[
    "email",
    "site",
    "pdf",
    "usb",
    "call",
    "workstation",
    "desk",
    "door",
    "badge",
]

AttemptOutcome = Literal["in_progress", "safe", "recovered", "failed"]

ROOM_VERSION = 1
BASE_POINTS = 10
POINTS_PER_DIFFICULTY = 2
MIN_OBJECTS = 1
MAX_OBJECTS = 5


def max_points_for(diff: int) -> int:
    """Return the maximum score for a room of the given difficulty (12..20)."""
    return BASE_POINTS + POINTS_PER_DIFFICULTY * diff


def _utcnow() -> datetime:
    """Return the current UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc)


class RoomObject(BaseModel):
    """A single object placed in the room."""

    id: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    kind: ObjKind
    ref: str = Field(min_length=1, max_length=128)
    # "<object_id>:link:<index>" — how the trainee reaches this object.
    via: str | None = Field(default=None, max_length=64)


class Room(BaseModel):
    """The generated room document stored in ``scenarios.room``."""

    v: int = ROOM_VERSION
    title: str = Field(min_length=3, max_length=120)
    brief: str = Field(min_length=20, max_length=400)
    diff: int = Field(ge=1, le=5)
    topic: str = ""
    intent: str = ""
    objs: list[RoomObject] = Field(min_length=MIN_OBJECTS, max_length=MAX_OBJECTS)
    goal: str = Field(min_length=1, max_length=200)

    @field_validator("objs")
    @classmethod
    def _unique_object_ids(cls, objs: list[RoomObject]) -> list[RoomObject]:
        """Reject duplicate object ids: goals address objects by id."""
        ids = [obj.id for obj in objs]
        if len(ids) != len(set(ids)):
            raise ValueError("object ids must be unique")
        return objs


class RuleSnapshot(BaseModel):
    """Immutable copy of the rule a scenario was generated from.

    Stored with the scenario so that editing or deleting the source rule (or
    its document) never changes the text a trainee was trained on. Rules are
    not versioned: re-uploading a document creates a new rule with a new id,
    so ``id`` + ``document_id`` already identify the original unambiguously.
    """

    id: str
    description: str
    topic: str
    audience: list[str] = Field(default_factory=list)
    document_id: str


class Scenario(BaseModel):
    """A generated room scenario as stored in the database.

    There is no ``rule_id`` column: the source rule is identified by
    ``rule_snapshot.id``, which is immutable and survives rule deletion. This
    keeps a single source of truth for "which rule produced this room".
    """

    id: str
    tenant_id: str
    rule_snapshot: RuleSnapshot | None = None
    department: str = "default"
    topic: str
    corpus_build_id: str
    fingerprint: str = ""
    max_points: int
    room: Room
    status: str = "generated"
    created_at: datetime = Field(default_factory=_utcnow)


class PublicRoomObject(BaseModel):
    """Object descriptor safe to hand to the trainee."""

    id: str
    kind: ObjKind
    ref: str
    via: str | None = None


class PublicScenario(BaseModel):
    """Trainee-facing scenario: everything except the answer key.

    ``goal``, artifact ``risk[]`` and ``benign`` never leave the server; the
    objective reaches the trainee as prose in ``brief``.
    """

    id: str
    title: str
    brief: str
    topic: str
    intent: str = ""
    diff: int
    max_points: int
    objs: list[PublicRoomObject]
    created_at: datetime

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> "PublicScenario":
        room = scenario.room
        return cls(
            id=scenario.id,
            title=room.title,
            brief=room.brief,
            topic=scenario.topic,
            intent=room.intent,
            diff=room.diff,
            max_points=scenario.max_points,
            created_at=scenario.created_at,
            objs=[
                PublicRoomObject(
                    id=obj.id, kind=obj.kind, ref=obj.ref, via=obj.via
                )
                for obj in room.objs
            ],
        )


class GenerateScenarioRequest(BaseModel):
    """Request body for generating a scenario for a single rule."""

    tenant_id: str = DEFAULT_TENANT_ID
    rule_id: str
    department: str = "default"
    benign: bool = False


class GenerateScenarioResponse(BaseModel):
    """Result of a successful scenario generation.

    Returned to the operator who triggered generation and therefore contains
    the full room (including the goal). Trainees use :class:`PublicScenario`.
    """

    scenario_id: str
    status: str
    scenario: Scenario


class BatchGenerateRequest(BaseModel):
    """Request body for generating scenarios per matching rule."""

    tenant_id: str
    department: str = "default"
    topic: str | None = None
    rooms_per_rule: int = Field(default=2, ge=1, le=5)
    benign_ratio: float = Field(default=0.2, ge=0.0, le=1.0)


class BatchGenerateResponse(BaseModel):
    """Result of a batch generation run."""

    generated: list[Scenario]
    skipped: list[str]
    errors: list[dict[str, str]]
    skipped_details: list[dict[str, str]] = Field(default_factory=list)
    total_generated: int
    total_skipped: int


class StartAttemptRequest(BaseModel):
    """Request body for starting a room attempt."""

    tenant_id: str = DEFAULT_TENANT_ID
    employee_id: str = DEFAULT_EMPLOYEE_ID


class SubmitEventRequest(BaseModel):
    """A single trainee action ``(verb, object)``."""

    verb: Verb
    obj: str


class AttemptEvent(BaseModel):
    """One recorded action in the attempt log."""

    verb: str
    obj: str
    at: datetime = Field(default_factory=_utcnow)


class Attempt(BaseModel):
    """A trainee's attempt at a room, with its event log."""

    id: str
    tenant_id: str
    scenario_id: str
    employee_id: str
    events: list[AttemptEvent] = Field(default_factory=list)
    outcome: AttemptOutcome = "in_progress"
    score: int | None = None
    max_points: int
    lessons: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None


class PublicLesson(BaseModel):
    """Mini-lesson shown after a mistake."""

    id: str
    title: str
    text: str


class PublicAttemptEvent(BaseModel):
    """Event with its evaluation, safe for the trainee."""

    verb: str
    obj: str
    level: Literal["soft", "hard"] | None = None
    pen: int = 0
    lesson: str | None = None


class AttemptState(BaseModel):
    """Trainee-facing attempt state returned by the attempts API."""

    attempt_id: str
    scenario_id: str
    employee_id: str
    outcome: AttemptOutcome
    score: int | None
    max_points: int
    blind: bool
    lessons: list[PublicLesson]
    events: list[PublicAttemptEvent]
    started_at: datetime
    finished_at: datetime | None
