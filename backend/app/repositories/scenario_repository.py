"""Async CRUD repository for generated scenarios."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import ScenarioORM
from ..models.scenario import (
    Scenario,
    ScenarioAction,
    ScenarioScoring,
)


class ScenarioRepository:
    """Translate between :class:`ScenarioORM` rows and Pydantic :class:`Scenario` DTOs."""

    @staticmethod
    def _to_orm(scenario: Scenario) -> ScenarioORM:
        return ScenarioORM(
            id=scenario.id,
            tenant_id=scenario.tenant_id,
            title=scenario.title,
            topic=scenario.topic,
            step_type=scenario.step_type,
            content=scenario.content,
            actions=[action.model_dump() for action in scenario.actions],
            feedback=scenario.feedback,
            scoring=scenario.scoring.model_dump(),
            department=scenario.department,
            rule_id=scenario.rule_id,
            status="generated",
        )

    @staticmethod
    def _to_scenario(orm: ScenarioORM) -> Scenario:
        return Scenario(
            id=orm.id,
            tenant_id=orm.tenant_id,
            title=orm.title,
            topic=orm.topic,
            step_type=orm.step_type,
            content=orm.content,
            actions=[ScenarioAction.model_validate(action) for action in orm.actions],
            feedback=orm.feedback,
            scoring=ScenarioScoring.model_validate(orm.scoring),
            department=orm.department or "default",
            rule_id=orm.rule_id,
            created_at=orm.created_at,
        )

    async def create(self, session: AsyncSession, scenario: Scenario) -> Scenario:
        """Insert a new scenario record and return the (unchanged) DTO."""
        session.add(self._to_orm(scenario))
        await session.flush()
        return scenario

    async def get(self, session: AsyncSession, scenario_id: str) -> Scenario | None:
        """Return a scenario by id, or ``None`` when it does not exist."""
        orm = await session.get(ScenarioORM, scenario_id)
        return self._to_scenario(orm) if orm is not None else None

    async def list(
        self, session: AsyncSession, tenant_id: str | None = None
    ) -> list[Scenario]:
        """List all scenarios, optionally filtered by tenant."""
        statement = select(ScenarioORM)
        if tenant_id is not None:
            statement = statement.where(ScenarioORM.tenant_id == tenant_id)
        result = await session.execute(statement)
        return [self._to_scenario(orm) for orm in result.scalars()]

    async def list_by_rule(
        self, session: AsyncSession, rule_id: str
    ) -> list[Scenario]:
        """List every scenario generated from a specific rule."""
        statement = select(ScenarioORM).where(ScenarioORM.rule_id == rule_id)
        result = await session.execute(statement)
        return [self._to_scenario(orm) for orm in result.scalars()]

    async def delete(self, session: AsyncSession, scenario_id: str) -> bool:
        """Remove a scenario record; return ``False`` when the id is unknown."""
        orm = await session.get(ScenarioORM, scenario_id)
        if orm is None:
            return False
        await session.delete(orm)
        await session.flush()
        return True
