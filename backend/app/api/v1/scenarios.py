"""FastAPI endpoints for room scenarios and starting attempts."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import DEFAULT_TENANT_ID
from ...core.database import get_db
from ...models.scenario import (
    AttemptState,
    BatchGenerateRequest,
    BatchGenerateResponse,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
    PublicScenario,
    StartAttemptRequest,
)
from ...services.scenario_service import ScenarioService, get_scenario_service

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])


def get_service() -> ScenarioService:
    """FastAPI dependency returning the scenario-service singleton."""
    return get_scenario_service()


@router.post("/generate", response_model=GenerateScenarioResponse, status_code=201)
async def generate_scenario(
    request: GenerateScenarioRequest,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> GenerateScenarioResponse:
    """Generate a training room for a single rule (operator endpoint)."""
    return await service.generate_scenario(session, request)


@router.post("/generate-all", response_model=BatchGenerateResponse, status_code=201)
async def generate_all_scenarios(
    request: BatchGenerateRequest,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> BatchGenerateResponse:
    """Generate one room per matching rule, continuing past per-rule failures."""
    return await service.generate_all_scenarios(session, request)


@router.get("", response_model=list[PublicScenario])
async def list_scenarios(
    tenant_id: str = DEFAULT_TENANT_ID,
    rule_id: str | None = None,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> list[PublicScenario]:
    """List trainee-facing scenarios, optionally filtered by rule."""
    if rule_id is not None:
        scenarios = await service.list_scenarios_by_rule(session, rule_id)
        return [PublicScenario.from_scenario(scenario) for scenario in scenarios]
    return await service.list_public_scenarios(session, tenant_id)


@router.get("/{scenario_id}", response_model=PublicScenario)
async def get_scenario(
    scenario_id: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> PublicScenario:
    """Retrieve a scenario without the answer key (goal, risks, benign)."""
    return await service.get_public_scenario(session, scenario_id, tenant_id)


@router.post(
    "/{scenario_id}/attempts", response_model=AttemptState, status_code=201
)
async def start_attempt(
    scenario_id: str,
    request: StartAttemptRequest,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> AttemptState:
    """Open a trainee attempt at a room."""
    attempt = await service.start_attempt(
        session, scenario_id, request.tenant_id, request.employee_id
    )
    return await service.attempt_state(session, attempt.id, request.tenant_id)


@router.delete("/{scenario_id}", status_code=204)
async def delete_scenario(
    scenario_id: str,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> None:
    """Soft-delete a scenario by id."""
    await service.delete_scenario(session, scenario_id)
