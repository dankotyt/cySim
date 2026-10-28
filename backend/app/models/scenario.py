"""Pydantic models for the scenario-generation module."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from ..core.config import DEFAULT_TENANT_ID
from ..core.topics import AttackType

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


class ScenarioContext(BaseModel):
    """Reference to the company rule the scenario is built around."""

    company_rule: str
    source: str
    page: int


class ScenarioScoring(BaseModel):
    """Scoring thresholds for the scenario."""

    max_points: int
    passing_score: int


class Scenario(BaseModel):
    """A fully generated training scenario."""

    id: str
    tenant_id: str
    title: str
    attack_type: AttackType
    context: ScenarioContext
    step_type: ScenarioStepType
    content: str
    actions: list[ScenarioAction]
    feedback: str
    correct_action: str
    scoring: ScenarioScoring
    department: str = "default"
    rule_id: str | None = None
    topics_used: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class GenerateScenarioRequest(BaseModel):
    """Request body for generating a scenario for a single rule."""

    tenant_id: str = DEFAULT_TENANT_ID
    rule_id: str
    department: str = "default"
    num_steps: int | None = Field(None, ge=1, le=10)


class GenerateScenarioResponse(BaseModel):
    """Result of a successful scenario generation."""

    scenario_id: str
    status: str
    scenario: Scenario


class BatchGenerateRequest(BaseModel):
    """Request body for generating one scenario per matching rule."""

    tenant_id: str
    department: str = "default"
    attack_types: list[AttackType] | None = None
    num_steps: int | None = Field(None, ge=1, le=10)


class BatchGenerateResponse(BaseModel):
    """Result of a batch generation run."""

    generated: list[Scenario]
    skipped: list[str]
    errors: list[dict[str, str]]
    total_generated: int
    total_skipped: int
