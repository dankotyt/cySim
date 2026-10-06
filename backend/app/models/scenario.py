"""Pydantic models for the scenario-generation module."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

# Top-level attack vectors the generator supports. They are a subset of the
# controlled topic vocabulary in rule_structurer.ALLOWED_TOPICS.
AttackType = Literal[
    "phishing",
    "vishing",
    "baiting",
    "pretexting",
    "tailgating",
    "quid_pro_quo",
    "social_media_osint",
    "usb_drop",
]

# The concrete attack types iterated by batch scenario generation.
ATTACK_TYPES: tuple[AttackType, ...] = (
    "phishing",
    "vishing",
    "baiting",
    "pretexting",
    "tailgating",
    "quid_pro_quo",
    "social_media_osint",
    "usb_drop",
)

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


class ScenarioStep(BaseModel):
    """One decision point within a scenario."""

    step_id: str
    type: ScenarioStepType
    content: str
    actions: list[ScenarioAction]
    feedback: str
    correct_action: str


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
    steps: list[ScenarioStep]
    scoring: ScenarioScoring
    department: str | None = None
    topics_used: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class GenerateScenarioRequest(BaseModel):
    """Request body for scenario generation."""

    tenant_id: str = "default"
    attack_type: AttackType
    department: str = "default"


class GenerateScenarioResponse(BaseModel):
    """Result of a successful scenario generation."""

    scenario_id: str
    status: str
    scenario: Scenario


class BatchGenerateRequest(BaseModel):
    """Request body for generating scenarios for a set of attack types."""

    tenant_id: str = "default"
    department: str = "default"
    attack_types: list[AttackType] | None = None


class BatchGenerateResponse(BaseModel):
    """Result of a batch generation run."""

    generated: list[Scenario]
    skipped: list[str]
    errors: list[dict[str, str]]
    total_generated: int
    total_skipped: int
