"""Scenario generation business logic: precomputed rules → prompt → LLM → persist."""
import json
import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..models.scenario import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
    Scenario,
)
from ..repositories.scenario_repository import ScenarioRepository
from ..repositories.security_rule_repository import SecurityRuleRepository
from .attack_queries import ATTACK_QUERIES
from .llm_provider import LLMProvider, get_llm_provider
from .scenario_context import build_scenario_context
from .scenario_prompts import SCENARIO_SYSTEM_PROMPT, build_scenario_prompt

logger = get_logger(__name__)


class ScenarioServiceError(Exception):
    """Base exception for scenario-service failures."""


class NoRulesFoundError(ScenarioServiceError):
    """Raised when no precomputed rules exist for the requested attack type."""


class ScenarioNotFoundError(ScenarioServiceError):
    """Raised when a scenario id is unknown."""


class ScenarioGenerationError(ScenarioServiceError):
    """Raised when the LLM output cannot be parsed into a valid scenario."""


class ScenarioService:
    """Facade exposing scenario generation (single and batch) and CRUD.

    Generation reads precomputed security rules from PostgreSQL (populated by
    :meth:`DocumentService.process_document`), packages them into a prompt, asks
    the LLM for a JSON scenario, validates it (with one clarification retry) and
    persists the result.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        rule_repository: SecurityRuleRepository | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.rule_repository = rule_repository or SecurityRuleRepository()
        self.llm_provider = llm_provider or get_llm_provider(self.settings)
        self.repository = ScenarioRepository()

    async def generate_scenario(
        self, session: AsyncSession, request: GenerateScenarioRequest
    ) -> GenerateScenarioResponse:
        """Retrieve precomputed rules, generate and persist a scenario."""
        rules = await self.rule_repository.list_by_category(
            session, request.tenant_id, request.attack_type
        )
        if not rules:
            raise NoRulesFoundError(
                f"No relevant rules found for tenant {request.tenant_id!r} "
                f"and attack type {request.attack_type!r}"
            )

        # Only the LLM sees the truncation; the database query stays unfiltered.
        rules_for_llm = rules[: request.top_k_rules]
        context = build_scenario_context(rules_for_llm)
        prompt = build_scenario_prompt(context, request.attack_type)

        scenario = self._generate_with_retry(prompt, request)
        await self.repository.create(session, scenario)

        logger.info(
            "Scenario generated: id=%s attack=%s tenant=%s",
            scenario.id,
            scenario.attack_type,
            scenario.tenant_id,
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
        generated: list[Scenario] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []

        for attack_type in ATTACK_QUERIES:
            try:
                response = await self.generate_scenario(
                    session,
                    GenerateScenarioRequest(
                        tenant_id=request.tenant_id,
                        attack_type=attack_type,
                        top_k_rules=request.top_k_rules,
                    ),
                )
            except NoRulesFoundError:
                skipped.append(attack_type)
                logger.warning(
                    "No rules for attack_type=%s tenant=%s",
                    attack_type,
                    request.tenant_id,
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

    def _generate_with_retry(
        self, prompt: str, request: GenerateScenarioRequest
    ) -> Scenario:
        raw = self.llm_provider.generate(prompt, system=SCENARIO_SYSTEM_PROMPT)
        try:
            return self._scenario_from_raw(raw, request)
        except ValueError as first_error:
            logger.warning("Scenario JSON invalid, retrying once: %s", first_error)
            correction = (
                f"{prompt}\n\n"
                f"Твой предыдущий ответ не прошёл валидацию JSON. Ошибка: {first_error}.\n"
                f"Верни ИСПРАВЛЕННЫЙ результат: строго валидный JSON-объект без markdown "
                f"и пояснений."
            )
            raw = self.llm_provider.generate(correction, system=SCENARIO_SYSTEM_PROMPT)
            try:
                return self._scenario_from_raw(raw, request)
            except ValueError as second_error:
                raise ScenarioGenerationError(
                    f"LLM returned invalid scenario JSON after retry: {second_error}"
                ) from second_error

    def _scenario_from_raw(
        self, raw: str, request: GenerateScenarioRequest
    ) -> Scenario:
        data = self._loads_json(raw)
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
                **fields,
            )
        except ValidationError as exc:
            raise ValueError(f"LLM JSON failed validation: {exc}") from exc

    @staticmethod
    def _loads_json(raw: str) -> dict:
        """Parse an LLM response, tolerating markdown fences and stray text."""
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end <= start:
                raise
            parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("LLM output must be a JSON object")
        return parsed

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
