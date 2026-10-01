"""FastAPI endpoints for scenario generation and management."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...models.scenario import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    GenerateScenarioRequest,
    GenerateScenarioResponse,
    Scenario,
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
    """Generate a training scenario for the given attack type."""
    return await service.generate_scenario(session, request)


@router.post("/generate-all", response_model=BatchGenerateResponse, status_code=201)
async def generate_all_scenarios(
    request: BatchGenerateRequest,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> BatchGenerateResponse:
    """Generate scenarios for every attack type, continuing past per-type failures."""
    return await service.generate_all_scenarios(session, request)


@router.get("/{scenario_id}", response_model=Scenario)
async def get_scenario(
    scenario_id: str,
    tenant_id: str | None = None,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> Scenario:
    """Retrieve a single scenario by id."""
    return await service.get_scenario(session, scenario_id, tenant_id)


@router.get("", response_model=list[Scenario])
async def list_scenarios(
    tenant_id: str | None = None,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> list[Scenario]:
    """List all scenarios, optionally filtered by tenant."""
    return await service.list_scenarios(session, tenant_id)


@router.delete("/{scenario_id}", status_code=204)
async def delete_scenario(
    scenario_id: str,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> None:
    """Delete a scenario by id."""
    await service.delete_scenario(session, scenario_id)
