"""Scenario generation business logic: one rule → prompt → LLM → persist."""
import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.topics import ATTACK_TYPES, ATTACK_TYPE_TOPICS
from ..models.document import SecurityRule
from ..models.scenario import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
    Scenario,
)
from ..repositories.department_repository import (
    DEFAULT_DEPARTMENT,
    DepartmentRepository,
)
from ..repositories.scenario_repository import ScenarioRepository
from ..repositories.security_rule_repository import SecurityRuleRepository
from ..utils.llm_json import parse_llm_json_object
from .llm_provider import LLMProvider, get_llm_provider
from .scenario_context import build_scenario_context
from .scenario_prompts import SCENARIO_SYSTEM_PROMPT, build_scenario_prompt
from .session_manager import SessionManager

logger = get_logger(__name__)


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
    """Raised when the LLM output cannot be parsed into a valid scenario."""


class ScenarioService:
    """Facade exposing scenario generation (single and batch) and CRUD.

    Each scenario is generated from exactly one :class:`SecurityRule`: batch
    generation produces one scenario per matching rule (whose topic is one of
    the requested attack types and is allowed for the department), while single
    generation takes an explicit rule id. LLM calls go through a shared
    :class:`SessionManager` so long batch runs stay within the context window.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        rule_repository: SecurityRuleRepository | None = None,
        llm_provider: LLMProvider | None = None,
        department_repository: DepartmentRepository | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.rule_repository = rule_repository or SecurityRuleRepository()
        self.llm_provider = llm_provider or get_llm_provider(self.settings)
        self.department_repository = department_repository or DepartmentRepository()
        self.session_manager = session_manager or SessionManager(
            self.llm_provider, self.settings.llm_num_ctx
        )
        self.repository = ScenarioRepository()

        # Batch-level session memory. These accumulate across every scenario in
        # a batch (and across calls) and are passed to the SessionManager as the
        # anchor, so a context reset re-injects all already-used topics and
        # titles for consistency.
        self._used_topics: list[str] = []
        self._generated_titles: list[str] = []

    async def generate_scenario(
        self, session: AsyncSession, request: GenerateScenarioRequest
    ) -> GenerateScenarioResponse:
        """Generate a single scenario for the rule named by ``request.rule_id``."""
        rule = await self.rule_repository.get(session, request.rule_id)
        if rule is None or rule.tenant_id != request.tenant_id:
            raise RuleNotFoundError(f"Rule not found: {request.rule_id!r}")

        num_steps = self._resolve_num_steps(request.num_steps)
        scenario = await self._generate_for_rule(
            session, rule, request.tenant_id, request.department, num_steps
        )
        logger.info(
            "Scenario generated: id=%s rule=%s tenant=%s department=%s",
            scenario.id,
            rule.id,
            request.tenant_id,
            request.department,
        )
        return GenerateScenarioResponse(
            scenario_id=scenario.id,
            status="generated",
            scenario=scenario,
        )

    async def generate_all_scenarios(
        self, session: AsyncSession, request: BatchGenerateRequest
    ) -> BatchGenerateResponse:
        """Generate one scenario per matching rule, isolating per-rule failures."""
        allowed_topics = await self._resolve_allowed_topics(
            session, request.tenant_id, request.department
        )
        attack_types = list(request.attack_types or ATTACK_TYPES)
        num_steps = self._resolve_num_steps(request.num_steps)

        generated: list[Scenario] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []

        for attack_type in attack_types:
            attack_topics = list(
                ATTACK_TYPE_TOPICS.get(attack_type, (attack_type,))
            )
            rules = await self.rule_repository.list_by_topics(
                session, request.tenant_id, attack_topics
            )
            filtered = [rule for rule in rules if rule.topic in allowed_topics]
            logger.info(
                "Found %d rules for attack_type=%s, %d allowed by department=%s",
                len(rules),
                attack_type,
                len(filtered),
                request.department,
            )

            if not filtered:
                skipped.append(attack_type)
                logger.warning(
                    "No rules for attack_type=%s tenant=%s department=%s",
                    attack_type,
                    request.tenant_id,
                    request.department,
                )
                continue

            for rule in filtered:
                try:
                    # Isolate each rule in its own savepoint so a failure in one
                    # does not poison the session for the remaining iterations.
                    async with session.begin_nested():
                        scenario = await self._generate_for_rule(
                            session,
                            rule,
                            request.tenant_id,
                            request.department,
                            num_steps,
                        )
                except ScenarioGenerationError as exc:
                    errors.append(
                        {"attack_type": attack_type, "error": str(exc)}
                    )
                    logger.error(
                        "Generation failed for rule=%s attack_type=%s: %s",
                        rule.id,
                        attack_type,
                        exc,
                    )
                    continue
                except Exception as exc:  # noqa: BLE001 - batch must not abort on one rule
                    errors.append(
                        {"attack_type": attack_type, "error": str(exc)}
                    )
                    logger.exception(
                        "Unexpected error for rule=%s attack_type=%s",
                        rule.id,
                        attack_type,
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
        num_steps: int,
    ) -> Scenario:
        """Generate and persist a scenario from a single rule."""
        if rule.topic not in ATTACK_TYPES:
            raise ScenarioGenerationError(
                f"Rule {rule.id!r} has non-attack topic {rule.topic!r}"
            )

        context = build_scenario_context([rule])
        prompt = build_scenario_prompt(
            context, rule.topic, department, num_steps
        )
        scenario = await self._generate_with_retry(
            prompt, tenant_id, department, rule
        )
        await self.repository.create(session, scenario)
        self._remember(scenario)
        return scenario

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

    def _resolve_num_steps(self, num_steps: int | None) -> int:
        """Return the configured number of steps, falling back to settings."""
        if num_steps is not None:
            return num_steps
        return self.settings.scenario_num_steps

    def _remember(self, scenario: Scenario) -> None:
        """Accumulate used topics and titles for the next session anchor."""
        for topic in scenario.topics_used:
            if topic not in self._used_topics:
                self._used_topics.append(topic)
        if scenario.title and scenario.title not in self._generated_titles:
            self._generated_titles.append(scenario.title)

    async def _generate_with_retry(
        self,
        prompt: str,
        tenant_id: str,
        department: str,
        rule: SecurityRule,
    ) -> Scenario:
        # Batch-level anchor: already-used topics and titles, not the current
        # scenario's attack type alone.
        anchor = [*self._used_topics, *self._generated_titles]
        raw = await self.session_manager.generate(
            prompt, system=SCENARIO_SYSTEM_PROMPT, anchor=anchor
        )
        try:
            return self._scenario_from_raw(raw, tenant_id, department, rule)
        except ValueError as first_error:
            logger.warning("Scenario JSON invalid, retrying once: %s", first_error)
            correction = (
                f"{prompt}\n\n"
                f"Твой предыдущий ответ не прошёл валидацию JSON. Ошибка: {first_error}.\n"
                f"Верни ИСПРАВЛЕННЫЙ результат: строго валидный JSON-объект без markdown "
                f"и пояснений."
            )
            raw = await self.session_manager.generate(
                correction, system=SCENARIO_SYSTEM_PROMPT, anchor=anchor
            )
            try:
                return self._scenario_from_raw(raw, tenant_id, department, rule)
            except ValueError as second_error:
                raise ScenarioGenerationError(
                    f"LLM returned invalid scenario JSON after retry: {second_error}"
                ) from second_error

    def _scenario_from_raw(
        self,
        raw: str,
        tenant_id: str,
        department: str,
        rule: SecurityRule,
    ) -> Scenario:
        data = parse_llm_json_object(raw)
        fields = {
            key: value
            for key, value in data.items()
            if key in {"title", "context", "steps", "scoring"}
        }
        try:
            return Scenario(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                attack_type=rule.topic,
                department=department,
                rule_id=rule.id,
                topics_used=[rule.topic],
                **fields,
            )
        except ValidationError as exc:
            raise ValueError(f"LLM JSON failed validation: {exc}") from exc

    async def get_scenario(
        self, session: AsyncSession, scenario_id: str, tenant_id: str | None = None
    ) -> Scenario:
        scenario = await self.repository.get(session, scenario_id)
        if scenario is None or (
            tenant_id is not None and scenario.tenant_id != tenant_id
        ):
            raise ScenarioNotFoundError(f"Scenario not found: {scenario_id}")
        return scenario

    async def list_scenarios(
        self, session: AsyncSession, tenant_id: str | None = None
    ) -> list[Scenario]:
        return await self.repository.list(session, tenant_id)

    async def list_scenarios_by_rule(
        self, session: AsyncSession, rule_id: str
    ) -> list[Scenario]:
        return await self.repository.list_by_rule(session, rule_id)

    async def delete_scenario(self, session: AsyncSession, scenario_id: str) -> None:
        if not await self.repository.delete(session, scenario_id):
            raise ScenarioNotFoundError(f"Scenario not found: {scenario_id}")


_service: ScenarioService | None = None


def get_scenario_service() -> ScenarioService:
    """Return a lazily-initialised singleton :class:`ScenarioService`."""
    global _service
    if _service is None:
        _service = ScenarioService()
    return _service
