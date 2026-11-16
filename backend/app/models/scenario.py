"""Pydantic models for the scenario-generation module."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from ..core.config import DEFAULT_TENANT_ID

# The interaction channel of a single scenario step.
ScenarioStepType = Literal[
    "email_view",
    "phone_call",
    "usb_insert",
    "web_page",
    "search_result",
]


def _utcnow() -> datetime:
    """Return the current UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc)


class ScenarioAction(BaseModel):
    """A single choice the trainee can make within a step."""

    id: str
    label: str
    is_correct: bool
    consequence: str
    points: int


class ScenarioScoring(BaseModel):
    """Scoring thresholds for the scenario."""

    max_points: int
    passing_score: int


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
    """A fully generated training scenario."""

    id: str
    tenant_id: str
    rule_id: str | None = None
    title: str
    topic: str
    step_type: ScenarioStepType
    content: str
    actions: list[ScenarioAction]
    feedback: str
    scoring: ScenarioScoring
    department: str = "default"
    rule_snapshot: RuleSnapshot | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class GenerateScenarioRequest(BaseModel):
    """Request body for generating a scenario for a single rule."""

    tenant_id: str = DEFAULT_TENANT_ID
    rule_id: str
    department: str = "default"


class GenerateScenarioResponse(BaseModel):
    """Result of a successful scenario generation."""

    scenario_id: str
    status: str
    scenario: Scenario


class BatchGenerateRequest(BaseModel):
    """Request body for generating one scenario per matching rule."""

    tenant_id: str
    department: str = "default"
    topic: str | None = None


class BatchGenerateResponse(BaseModel):
    """Result of a batch generation run."""

    generated: list[Scenario]
    skipped: list[str]
    errors: list[dict[str, str]]
    total_generated: int
    total_skipped: int
