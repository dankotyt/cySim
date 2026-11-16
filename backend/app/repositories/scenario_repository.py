"""Async CRUD repository for generated scenarios."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import ScenarioORM
from ..models.scenario import (
    RuleSnapshot,
    Scenario,
    ScenarioAction,
    ScenarioScoring,
)


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ScenarioRepository:
    """Translate between :class:`ScenarioORM` rows and Pydantic :class:`Scenario` DTOs.

    Deletion is soft: a scenario removed together with its rule or document is
    hidden from normal queries but stays in the database for analytics and for
    the employee's training history.
    """

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
            rule_snapshot=(
                scenario.rule_snapshot.model_dump()
                if scenario.rule_snapshot is not None
                else None
            ),
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
            rule_snapshot=(
                RuleSnapshot.model_validate(orm.rule_snapshot)
                if orm.rule_snapshot
                else None
            ),
            created_at=orm.created_at,
        )

    async def create(self, session: AsyncSession, scenario: Scenario) -> Scenario:
        """Insert a new scenario record and return the (unchanged) DTO."""
        session.add(self._to_orm(scenario))
        await session.flush()
        return scenario

    async def get(
        self,
        session: AsyncSession,
        scenario_id: str,
        include_deleted: bool = False,
    ) -> Scenario | None:
        """Return a scenario by id, or ``None`` when it is missing/deleted."""
        statement = select(ScenarioORM).where(ScenarioORM.id == scenario_id)
        if not include_deleted:
            statement = statement.where(ScenarioORM.deleted_at.is_(None))
        orm = (await session.execute(statement)).scalar_one_or_none()
        return self._to_scenario(orm) if orm is not None else None

    async def list_scenarios(
        self,
        session: AsyncSession,
        tenant_id: str | None = None,
        include_deleted: bool = False,
    ) -> list[Scenario]:
        """List scenarios, optionally filtered by tenant."""
        statement = select(ScenarioORM)
        if tenant_id is not None:
            statement = statement.where(ScenarioORM.tenant_id == tenant_id)
        if not include_deleted:
            statement = statement.where(ScenarioORM.deleted_at.is_(None))
        statement = statement.order_by(ScenarioORM.created_at)
        result = await session.execute(statement)
        return [self._to_scenario(orm) for orm in result.scalars()]

    async def list_by_rule(
        self,
        session: AsyncSession,
        rule_id: str,
        include_deleted: bool = False,
    ) -> list[Scenario]:
        """List every scenario generated from a specific rule."""
        statement = select(ScenarioORM).where(ScenarioORM.rule_id == rule_id)
        if not include_deleted:
            statement = statement.where(ScenarioORM.deleted_at.is_(None))
        result = await session.execute(statement)
        return [self._to_scenario(orm) for orm in result.scalars()]

    async def delete(self, session: AsyncSession, scenario_id: str) -> bool:
        """Soft-delete a scenario; return ``False`` when it is unknown."""
        orm = await session.get(ScenarioORM, scenario_id)
        if orm is None or orm.deleted_at is not None:
            return False
        orm.deleted_at = _utcnow()
        await session.flush()
        return True

    async def soft_delete_by_rule_ids(
        self, session: AsyncSession, rule_ids: list[str]
    ) -> int:
        """Soft-delete every non-deleted scenario linked to ``rule_ids``."""
        if not rule_ids:
            return 0
        statement = (
            update(ScenarioORM)
            .where(
                ScenarioORM.rule_id.in_(rule_ids),
                ScenarioORM.deleted_at.is_(None),
            )
            .values(deleted_at=_utcnow())
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount
