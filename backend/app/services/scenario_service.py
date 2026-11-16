"""Scenario generation and trainee-attempt business logic (room contract v1)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..models.document import SecurityRule
from ..models.scenario import (
    Attempt,
    AttemptEvent,
    AttemptState,
    BatchGenerateRequest,
    BatchGenerateResponse,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
    PublicAttemptEvent,
    PublicLesson,
    PublicScenario,
    RuleSnapshot,
    Scenario,
    max_points_for,
)
from ..repositories.department_repository import (
    DEFAULT_DEPARTMENT,
    DepartmentRepository,
)
from ..repositories.scenario_attempt_repository import ScenarioAttemptRepository
from ..repositories.scenario_repository import ScenarioRepository
from ..repositories.security_rule_repository import SecurityRuleRepository
from .llm_provider import LLMProvider, get_llm_provider
from .scenario_generation import (
    AppliedEvent,
    Evaluation,
    EventEngine,
    RoomGenerator,
    get_resources,
    room_fingerprint,
)
from .session_manager import SessionManager

logger = get_logger(__name__)


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ScenarioServiceError(Exception):
    """Base exception for scenario-service failures."""


class NoRulesFoundError(ScenarioServiceError):
    """Raised when no rules match the requested attack types and department."""


class RuleNotFoundError(ScenarioServiceError):
    """Raised when a rule id is unknown or belongs to another tenant."""


class DepartmentNotFoundError(ScenarioServiceError):
    """Raised when a requested department does not exist for the tenant."""


class ScenarioNotFoundError(ScenarioServiceError):
    """Raised when a scenario id is unknown."""


class ScenarioGenerationError(ScenarioServiceError):
    """Raised when no valid room could be produced for a rule."""


class AttemptNotFoundError(ScenarioServiceError):
    """Raised when an attempt id is unknown or belongs to another tenant."""


class AttemptClosedError(ScenarioServiceError):
    """Raised when an event is submitted to a finished attempt."""


class ScenarioService:
    """Facade over room generation, scenario CRUD and trainee attempts.

    Each scenario is generated from exactly one :class:`SecurityRule`: batch
    generation produces one room per matching rule, while single generation
    takes an explicit rule id. Rooms are validated (L0-L3) and de-duplicated by
    structural fingerprint; a rule that cannot be generated falls back to a
    deterministic fixture room instead of failing the run.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        rule_repository: SecurityRuleRepository | None = None,
        llm_provider: LLMProvider | None = None,
        department_repository: DepartmentRepository | None = None,
        session_manager: SessionManager | None = None,
        room_generator: RoomGenerator | None = None,
        scenario_repository: ScenarioRepository | None = None,
        attempt_repository: ScenarioAttemptRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.rule_repository = rule_repository or SecurityRuleRepository()
        self.llm_provider = llm_provider or get_llm_provider(self.settings)
        self.department_repository = department_repository or DepartmentRepository()
        self.session_manager = session_manager or SessionManager(
            self.llm_provider, self.settings.llm_num_ctx
        )
        self.room_generator = room_generator or RoomGenerator(self.session_manager)
        self.repository = scenario_repository or ScenarioRepository()
        self.attempt_repository = attempt_repository or ScenarioAttemptRepository()

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate_scenario(
        self, session: AsyncSession, request: GenerateScenarioRequest
    ) -> GenerateScenarioResponse:
        """Generate a single room for the rule named by ``request.rule_id``."""
        rule = await self.rule_repository.get_for_tenant(
            session, request.rule_id, request.tenant_id
        )
        if rule is None:
            raise RuleNotFoundError(f"Rule not found: {request.rule_id!r}")

        recent = await self.repository.recent_fingerprints(
            session, request.tenant_id
        )
        scenario, source = await self._generate_for_rule(
            session, rule, request.tenant_id, request.department, recent
        )
        logger.info(
            "Scenario generated: id=%s rule=%s tenant=%s department=%s source=%s",
            scenario.id,
            rule.id,
            request.tenant_id,
            request.department,
            source,
        )
        return GenerateScenarioResponse(
            scenario_id=scenario.id,
            status="fallback" if source == "fallback" else "generated",
            scenario=scenario,
        )

    async def generate_all_scenarios(
        self, session: AsyncSession, request: BatchGenerateRequest
    ) -> BatchGenerateResponse:
        """Generate one room per matching rule, isolating per-rule failures."""
        allowed_topics = await self._resolve_allowed_topics(
            session, request.tenant_id, request.department
        )

        rules = await self.rule_repository.list_by_tenant(
            session, request.tenant_id
        )

        if request.topic:
            candidates = [rule for rule in rules if rule.topic == request.topic]
        else:
            candidates = rules

        filtered = [rule for rule in candidates if rule.topic in allowed_topics]
        logger.info(
            "Batch generation: %d rules, %d allowed by department=%s",
            len(rules), len(filtered), request.department,
        )

        skipped: list[str] = []
        if not filtered:
            skipped.append(request.topic or "all")
            logger.warning(
                "No rules to generate for tenant=%s department=%s topic=%s",
                request.tenant_id, request.department, request.topic,
            )
            return BatchGenerateResponse(
                generated=[], skipped=skipped, errors=[],
                total_generated=0, total_skipped=len(skipped),
            )

        recent = await self.repository.recent_fingerprints(
            session, request.tenant_id
        )
        generated: list[Scenario] = []
        errors: list[dict[str, str]] = []

        for rule in filtered:
            try:
                async with session.begin_nested():
                    scenario, _source = await self._generate_for_rule(
                        session, rule, request.tenant_id, request.department, recent
                    )
            except Exception as exc:  # noqa: BLE001 — batch must not abort on one rule
                errors.append(
                    {"rule_id": rule.id, "topic": rule.topic, "error": str(exc)}
                )
                logger.exception(
                    "Unexpected error for rule=%s topic=%s", rule.id, rule.topic,
                )
                continue
            else:
                generated.append(scenario)

        return BatchGenerateResponse(
            generated=generated,
            skipped=skipped,
            errors=errors,
            total_generated=len(generated),
            total_skipped=len(skipped),
        )

    async def _generate_for_rule(
        self,
        session: AsyncSession,
        rule: SecurityRule,
        tenant_id: str,
        department: str,
        recent_fingerprints: set[str],
    ) -> tuple[Scenario, str]:
        """Generate, validate and persist one room."""
        result = await self.room_generator.generate(
            rule=rule,
            tenant_id=tenant_id,
            department=department,
            recent_fingerprints=recent_fingerprints,
        )
        resources = get_resources()
        scenario = Scenario(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            rule_snapshot=self._rule_snapshot(rule),
            department=department,
            topic=rule.topic,
            corpus_build_id=resources.build_id,
            fingerprint=room_fingerprint(result.room),
            max_points=max_points_for(result.room.diff),
            room=result.room,
        )
        await self.repository.create(session, scenario)
        recent_fingerprints.add(scenario.fingerprint)
        return scenario, result.source

    async def _resolve_allowed_topics(
        self, session: AsyncSession, tenant_id: str, department: str
    ) -> list[str]:
        """Return the topic allowlist for a department.

        The reserved ``default`` department is unrestricted and is created
        lazily with the full :data:`ALLOWED_TOPICS` vocabulary on first access;
        every other department must already exist in the ``departments`` table.
        """
        if department == DEFAULT_DEPARTMENT:
            stored = await self.department_repository.get_or_create_default(
                session, tenant_id
            )
            return stored.allowed_topics
        stored = await self.department_repository.get_by_name(
            session, tenant_id, department
        )
        if stored is None:
            raise DepartmentNotFoundError(
                f"Department not found: {department!r} for tenant {tenant_id!r}"
            )
        return stored.allowed_topics

    @staticmethod
    def _rule_snapshot(rule: SecurityRule) -> RuleSnapshot:
        """Capture the rule text so later edits/deletions cannot rewrite history."""
        return RuleSnapshot(
            id=rule.id,
            description=rule.description,
            topic=rule.topic,
            audience=list(rule.audience),
            document_id=rule.document_id,
        )

    # ------------------------------------------------------------------
    # Scenario reads
    # ------------------------------------------------------------------

    async def get_scenario(
        self,
        session: AsyncSession,
        scenario_id: str,
        tenant_id: str | None = None,
        include_deleted: bool = False,
    ) -> Scenario:
        scenario = await self.repository.get(
            session, scenario_id, include_deleted=include_deleted
        )
        if scenario is None or (
            tenant_id is not None and scenario.tenant_id != tenant_id
        ):
            raise ScenarioNotFoundError(f"Scenario not found: {scenario_id}")
        return scenario

    async def get_public_scenario(
        self, session: AsyncSession, scenario_id: str, tenant_id: str
    ) -> PublicScenario:
        """Return the trainee-facing view (no goal, no artifact metadata)."""
        scenario = await self.get_scenario(session, scenario_id, tenant_id)
        return PublicScenario.from_scenario(scenario)

    async def list_scenarios(
        self,
        session: AsyncSession,
        tenant_id: str | None = None,
        include_deleted: bool = False,
    ) -> list[Scenario]:
        return await self.repository.list_scenarios(
            session, tenant_id, include_deleted=include_deleted
        )

    async def list_public_scenarios(
        self, session: AsyncSession, tenant_id: str
    ) -> list[PublicScenario]:
        scenarios = await self.list_scenarios(session, tenant_id)
        return [PublicScenario.from_scenario(scenario) for scenario in scenarios]

    async def list_scenarios_by_rule(
        self,
        session: AsyncSession,
        rule_id: str,
        include_deleted: bool = False,
    ) -> list[Scenario]:
        return await self.repository.list_by_rule(
            session, rule_id, include_deleted=include_deleted
        )

    async def delete_scenario(self, session: AsyncSession, scenario_id: str) -> None:
        if not await self.repository.delete(session, scenario_id):
            raise ScenarioNotFoundError(f"Scenario not found: {scenario_id}")

    # ------------------------------------------------------------------
    # Attempts
    # ------------------------------------------------------------------

    async def start_attempt(
        self,
        session: AsyncSession,
        scenario_id: str,
        tenant_id: str,
        employee_id: str,
    ) -> Attempt:
        """Open a new attempt for a trainee on a scenario."""
        scenario = await self.repository.get(session, scenario_id)
        if scenario is None or scenario.tenant_id != tenant_id:
            raise ScenarioNotFoundError(f"Scenario not found: {scenario_id}")

        attempt = Attempt(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            employee_id=employee_id,
            max_points=scenario.max_points,
        )
        await self.attempt_repository.create(session, attempt)
        return attempt

    async def submit_event(
        self,
        session: AsyncSession,
        attempt_id: str,
        tenant_id: str,
        verb: str,
        obj: str,
    ) -> Attempt:
        """Append an action to the log and re-evaluate the attempt."""
        attempt = await self._get_attempt(session, attempt_id, tenant_id)
        if attempt.outcome != "in_progress":
            raise AttemptClosedError(
                f"Attempt {attempt_id} is already finished ({attempt.outcome})"
            )
        scenario = await self.repository.get(
            session, attempt.scenario_id, include_deleted=True
        )
        if scenario is None:
            raise ScenarioNotFoundError(
                f"Scenario not found: {attempt.scenario_id}"
            )

        attempt.events.append(AttemptEvent(verb=verb, obj=obj))
        evaluation = self._evaluate(scenario, attempt)
        attempt.outcome = evaluation.outcome
        attempt.score = evaluation.score
        attempt.lessons = list(evaluation.lessons)
        if evaluation.outcome != "in_progress":
            attempt.finished_at = _utcnow()

        await self.attempt_repository.update(session, attempt)
        return attempt

    async def get_attempt(
        self, session: AsyncSession, attempt_id: str, tenant_id: str
    ) -> Attempt:
        return await self._get_attempt(session, attempt_id, tenant_id)

    async def list_attempts(
        self,
        session: AsyncSession,
        tenant_id: str,
        employee_id: str | None = None,
        scenario_id: str | None = None,
    ) -> list[Attempt]:
        return await self.attempt_repository.list_attempts(
            session, tenant_id, employee_id=employee_id, scenario_id=scenario_id
        )

    async def attempt_state(
        self, session: AsyncSession, attempt_id: str, tenant_id: str
    ) -> AttemptState:
        """Return the trainee-facing attempt state."""
        attempt = await self._get_attempt(session, attempt_id, tenant_id)
        return await self._build_state(session, attempt)

    async def list_attempt_states(
        self,
        session: AsyncSession,
        tenant_id: str,
        employee_id: str | None = None,
        scenario_id: str | None = None,
    ) -> list[AttemptState]:
        """Return trainee-facing states for every matching attempt."""
        attempts = await self.list_attempts(
            session, tenant_id, employee_id=employee_id, scenario_id=scenario_id
        )
        return [await self._build_state(session, attempt) for attempt in attempts]

    async def _build_state(
        self, session: AsyncSession, attempt: Attempt
    ) -> AttemptState:
        """Replay the log into a public state; tolerate a deleted scenario."""
        scenario = await self.repository.get(
            session, attempt.scenario_id, include_deleted=True
        )
        if scenario is not None:
            evaluation = self._evaluate(scenario, attempt)
            applied = evaluation.events
            blind = evaluation.blind
        else:
            applied = tuple(
                AppliedEvent(verb=event.verb, obj=event.obj)
                for event in attempt.events
            )
            blind = False

        return AttemptState(
            attempt_id=attempt.id,
            scenario_id=attempt.scenario_id,
            employee_id=attempt.employee_id,
            outcome=attempt.outcome,
            score=attempt.score,
            max_points=attempt.max_points,
            blind=blind,
            lessons=self._public_lessons(attempt.lessons),
            events=[
                PublicAttemptEvent(
                    verb=event.verb,
                    obj=event.obj,
                    level=event.level,
                    pen=event.pen,
                    lesson=event.lesson,
                )
                for event in applied
            ],
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
        )

    @staticmethod
    def _public_lessons(lesson_ids: list[str]) -> list[PublicLesson]:
        """Resolve stored lesson ids into their public text."""
        catalog = get_resources().lessons
        lessons: list[PublicLesson] = []
        for lesson_id in lesson_ids:
            lesson = catalog.get(lesson_id)
            if lesson is not None:
                lessons.append(
                    PublicLesson(id=lesson.id, title=lesson.title, text=lesson.text)
                )
        return lessons

    @staticmethod
    def _evaluate(scenario: Scenario, attempt: Attempt) -> Evaluation:
        engine = EventEngine(scenario.room, get_resources().artifacts)
        return engine.evaluate(
            [(event.verb, event.obj) for event in attempt.events]
        )

    async def _get_attempt(
        self, session: AsyncSession, attempt_id: str, tenant_id: str
    ) -> Attempt:
        attempt = await self.attempt_repository.get(session, attempt_id)
        if attempt is None or attempt.tenant_id != tenant_id:
            raise AttemptNotFoundError(f"Attempt not found: {attempt_id}")
        return attempt


_service: ScenarioService | None = None


def get_scenario_service() -> ScenarioService:
    """Return a lazily-initialised singleton :class:`ScenarioService`."""
    global _service
    if _service is None:
        _service = ScenarioService()
    return _service
