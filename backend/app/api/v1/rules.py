"""FastAPI endpoints for structured security rules."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import DEFAULT_TENANT_ID
from ...core.database import get_db
from ...core.topics import ALLOWED_TOPICS
from ...models.document import SecurityRule
from ...repositories.scenario_repository import ScenarioRepository
from ...repositories.security_rule_repository import SecurityRuleRepository

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


def get_repository() -> SecurityRuleRepository:
    """FastAPI dependency returning a rule repository."""
    return SecurityRuleRepository()


def get_scenario_repository() -> ScenarioRepository:
    """FastAPI dependency returning a scenario repository."""
    return ScenarioRepository()


@router.get("", response_model=list[SecurityRule])
async def list_rules(
    tenant_id: str = DEFAULT_TENANT_ID,
    topic: str | None = Query(None, description="Filter by rule topic"),
    document_id: str | None = Query(None, description="Filter by source document"),
    limit: int | None = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    repository: SecurityRuleRepository = Depends(get_repository),
) -> list[SecurityRule]:
    """List non-deleted rules for a tenant with optional filters."""
    if topic is not None and topic not in ALLOWED_TOPICS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown topic {topic!r}; allowed: {ALLOWED_TOPICS}",
        )
    return await repository.list_by_filters(
        session,
        tenant_id,
        topic=topic,
        document_id=document_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{rule_id}", response_model=SecurityRule)
async def get_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_db),
    repository: SecurityRuleRepository = Depends(get_repository),
) -> SecurityRule:
    """Retrieve a single non-deleted rule by id."""
    rule = await repository.get(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_db),
    repository: SecurityRuleRepository = Depends(get_repository),
    scenario_repository: ScenarioRepository = Depends(get_scenario_repository),
) -> None:
    """Soft-delete a rule and its scenarios (rows stay for analytics)."""
    if not await repository.delete(session, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    await scenario_repository.soft_delete_by_rule_ids(session, [rule_id])
