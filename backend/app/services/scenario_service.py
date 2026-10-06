"""Scenario generation business logic: topic filtering → prompt → LLM → persist."""
import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.topics import ALLOWED_TOPICS, ATTACK_TYPE_TOPICS
from ..models.scenario import (
    ATTACK_TYPES,
    AttackType,
    BatchGenerateRequest,
    BatchGenerateResponse,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
    Scenario,
)
from ..repositories.department_repository import DepartmentRepository
from ..repositories.scenario_repository import ScenarioRepository
from ..repositories.security_rule_repository import SecurityRuleRepository
from ..utils.llm_json import parse_llm_json_object
from .llm_provider import LLMProvider, get_llm_provider
from .scenario_context import build_scenario_context
from .scenario_prompts import SCENARIO_SYSTEM_PROMPT, build_scenario_prompt
from .session_manager import SessionManager

logger = get_logger(__name__)

# The reserved department name that maps to the full topic vocabulary.
DEFAULT_DEPARTMENT = "default"


class ScenarioServiceError(Exception):
    """Base exception for scenario-service failures."""


class NoRulesFoundError(ScenarioServiceError):
    """Raised when no rules match the attack type topics and department filter."""


class DepartmentNotFoundError(ScenarioServiceError):
    """Raised when a requested department does not exist for the tenant."""


class ScenarioNotFoundError(ScenarioServiceError):
    """Raised when a scenario id is unknown."""


class ScenarioGenerationError(ScenarioServiceError):
    """Raised when the LLM output cannot be parsed into a valid scenario."""


class ScenarioService:
    """Facade exposing scenario generation (single and batch) and CRUD.

    Generation selects the tenant's structured security rules by SQL topic
    filtering: rules whose topic belongs to the attack type's topics and to the
    department's ``allowed_topics`` are handed to the LLM for a JSON scenario
    (with one clarification retry). LLM calls go through a shared
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

        # Cross-call session memory: passed as the SessionManager anchor so a
        # reset re-injects already-used topics and titles for consistency.
        self._used_topics: list[str] = []
        self._generated_titles: list[str] = []

    async def generate_scenario(
        self, session: AsyncSession, request: GenerateScenarioRequest
    ) -> GenerateScenarioResponse:
        """Select rules by topic + department, generate and persist a scenario."""
        allowed_topics = await self._resolve_allowed_topics(
            session, request.tenant_id, request.department
        )
        attack_topics = list(
            ATTACK_TYPE_TOPICS.get(request.attack_type, (request.attack_type,))
        )

        rules = await self.rule_repository.list_by_topics(
            session, request.tenant_id, attack_topics
        )
        logger.info(
            "Found %d rules for attack_type=%s tenant=%s",
            len(rules),
            request.attack_type,
            request.tenant_id,
        )

        filtered = [rule for rule in rules if rule.topic in allowed_topics]
        logger.info(
            "Department filter removed %d of %d rules for department=%s",
            len(rules) - len(filtered),
            len(rules),
            request.department,
        )

        if not filtered:
            raise NoRulesFoundError(
                f"No rules found for topic(s) {attack_topics!r} in department "
                f"{request.department!r} (tenant {request.tenant_id!r})"
            )

        topics_used = sorted({rule.topic for rule in filtered})
        logger.info(
            "Passing %d rules to LLM (topics=%s)",
            len(filtered),
            ", ".join(topics_used),
        )

        context = build_scenario_context(filtered)
        prompt = build_scenario_prompt(
            context, request.attack_type, request.department
        )
        scenario = await self._generate_with_retry(prompt, request, topics_used)
        await self.repository.create(session, scenario)
        self._remember(scenario)

        logger.info(
            "Scenario generated: id=%s attack=%s tenant=%s department=%s",
            scenario.id,
            scenario.attack_type,
            scenario.tenant_id,
            scenario.department,
        )
        return GenerateScenarioResponse(
            scenario_id=scenario.id,
            status="generated",
            scenario=scenario,
        )

    async def generate_all_scenarios(
        self, session: AsyncSession, request: BatchGenerateRequest
    ) -> BatchGenerateResponse:
        """Generate one scenario per attack type, isolating per-type failures."""
        attack_types = list(request.attack_types or ATTACK_TYPES)
        generated: list[Scenario] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []

        for attack_type in attack_types:
            try:
                # Isolate each attack type in its own savepoint so a failure in
                # one does not poison the session for the remaining iterations.
                async with session.begin_nested():
                    response = await self.generate_scenario(
                        session,
                        GenerateScenarioRequest(
                            tenant_id=request.tenant_id,
                            attack_type=attack_type,
                            department=request.department,
                        ),
                    )
            except NoRulesFoundError:
                skipped.append(attack_type)
                logger.warning(
                    "No rules for attack_type=%s tenant=%s department=%s",
                    attack_type,
                    request.tenant_id,
                    request.department,
                )
                continue
            except ScenarioGenerationError as exc:
                errors.append({"attack_type": attack_type, "error": str(exc)})
                logger.error(
                    "Generation failed for attack_type=%s tenant=%s: %s",
                    attack_type,
                    request.tenant_id,
                    exc,
                )
                continue
            except Exception as exc:  # noqa: BLE001 - batch must not abort on one type
                errors.append({"attack_type": attack_type, "error": str(exc)})
                logger.exception(
                    "Unexpected error for attack_type=%s tenant=%s",
                    attack_type,
                    request.tenant_id,
                )
                continue
            else:
                generated.append(response.scenario)

        return BatchGenerateResponse(
            generated=generated,
            skipped=skipped,
            errors=errors,
            total_generated=len(generated),
            total_skipped=len(skipped),
        )

    async def _resolve_allowed_topics(
        self, session: AsyncSession, tenant_id: str, department: str
    ) -> list[str]:
        """Return the topic allowlist for a department.

        The reserved ``default`` department is unrestricted and maps to the full
        :data:`ALLOWED_TOPICS` vocabulary; every other department must exist in
        the ``departments`` table.
        """
        if department == DEFAULT_DEPARTMENT:
            return list(ALLOWED_TOPICS)
        stored = await self.department_repository.get_by_name(
            session, tenant_id, department
        )
        if stored is None:
            raise DepartmentNotFoundError(
                f"Department not found: {department!r} for tenant {tenant_id!r}"
            )
        return stored.allowed_topics

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
        request: GenerateScenarioRequest,
        topics_used: list[str],
    ) -> Scenario:
        anchor = [*self._used_topics, *self._generated_titles]
        raw = await self.session_manager.generate(
            prompt, system=SCENARIO_SYSTEM_PROMPT, anchor=anchor
        )
        try:
            return self._scenario_from_raw(raw, request, topics_used)
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
                return self._scenario_from_raw(raw, request, topics_used)
            except ValueError as second_error:
                raise ScenarioGenerationError(
                    f"LLM returned invalid scenario JSON after retry: {second_error}"
                ) from second_error

    def _scenario_from_raw(
        self,
        raw: str,
        request: GenerateScenarioRequest,
        topics_used: list[str],
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
                tenant_id=request.tenant_id,
                attack_type=request.attack_type,
                department=request.department,
                topics_used=list(topics_used),
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
