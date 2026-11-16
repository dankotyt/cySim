"""FastAPI endpoints for trainee attempts at rooms."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import DEFAULT_TENANT_ID
from ...core.database import get_db
from ...models.scenario import AttemptState, SubmitEventRequest
from ...services.scenario_service import ScenarioService, get_scenario_service

router = APIRouter(prefix="/api/v1/attempts", tags=["attempts"])


def get_service() -> ScenarioService:
    """FastAPI dependency returning the scenario-service singleton."""
    return get_scenario_service()


@router.get("", response_model=list[AttemptState])
async def list_attempts(
    tenant_id: str = DEFAULT_TENANT_ID,
    employee_id: str | None = None,
    scenario_id: str | None = None,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> list[AttemptState]:
    """List attempts for a tenant, optionally narrowed to employee/scenario."""
    return await service.list_attempt_states(
        session, tenant_id, employee_id=employee_id, scenario_id=scenario_id
    )


@router.get("/{attempt_id}", response_model=AttemptState)
async def get_attempt(
    attempt_id: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> AttemptState:
    """Return the current state of an attempt."""
    return await service.attempt_state(session, attempt_id, tenant_id)


@router.post("/{attempt_id}/events", response_model=AttemptState)
async def submit_event(
    attempt_id: str,
    request: SubmitEventRequest,
    tenant_id: str = DEFAULT_TENANT_ID,
    session: AsyncSession = Depends(get_db),
    service: ScenarioService = Depends(get_service),
) -> AttemptState:
    """Record a trainee action and return the re-evaluated state."""
    attempt = await service.submit_event(
        session, attempt_id, tenant_id, request.verb, request.obj
    )
    return await service.attempt_state(session, attempt.id, tenant_id)
