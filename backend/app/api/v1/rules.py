"""FastAPI endpoints for structured security rules."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import DEFAULT_TENANT_ID
from ...core.database import get_db
from ...models.document import SecurityRule
from ...repositories.security_rule_repository import SecurityRuleRepository

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


def get_repository() -> SecurityRuleRepository:
    """FastAPI dependency returning a rule repository."""
    return SecurityRuleRepository()


@router.get("", response_model=list[SecurityRule])
async def list_rules(
    tenant_id: str = DEFAULT_TENANT_ID,
    session: AsyncSession = Depends(get_db),
    repository: SecurityRuleRepository = Depends(get_repository),
) -> list[SecurityRule]:
    """List every structured rule for a tenant."""
    return await repository.list_by_tenant(session, tenant_id)


@router.get("/{rule_id}", response_model=SecurityRule)
async def get_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_db),
    repository: SecurityRuleRepository = Depends(get_repository),
) -> SecurityRule:
    """Retrieve a single rule by id."""
    rule = await repository.get(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_db),
    repository: SecurityRuleRepository = Depends(get_repository),
) -> None:
    """Delete a rule; scenarios linked to it are removed via FK cascade."""
    if not await repository.delete(session, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
