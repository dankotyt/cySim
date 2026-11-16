"""Async CRUD repository for generated room scenarios."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import ScenarioORM
from ..models.scenario import Room, RuleSnapshot, Scenario


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ScenarioRepository:
    """Translate between :class:`ScenarioORM` rows and :class:`Scenario` DTOs.

    Deletion is soft: a scenario removed together with its rule or document is
    hidden from normal queries but stays in the database for analytics and for
    the employee's training history. Rows written before the room contract
    (``room IS NULL``) are no longer readable and are therefore skipped.
    """

    @staticmethod
    def _to_orm(scenario: Scenario) -> ScenarioORM:
        return ScenarioORM(
            id=scenario.id,
            tenant_id=scenario.tenant_id,
            title=scenario.room.title,
            topic=scenario.topic,
            room=scenario.room.model_dump(),
            max_points=scenario.max_points,
            diff=scenario.room.diff,
            fingerprint=scenario.fingerprint,
            corpus_build_id=scenario.corpus_build_id,
            rule_snapshot=(
                scenario.rule_snapshot.model_dump()
                if scenario.rule_snapshot is not None
                else None
            ),
            department=scenario.department,
            status=scenario.status,
        )

    @staticmethod
    def _to_scenario(orm: ScenarioORM) -> Scenario:
        return Scenario(
            id=orm.id,
            tenant_id=orm.tenant_id,
            rule_snapshot=(
                RuleSnapshot.model_validate(orm.rule_snapshot)
                if orm.rule_snapshot
                else None
            ),
            department=orm.department or "default",
            topic=orm.topic,
            corpus_build_id=orm.corpus_build_id,
            fingerprint=orm.fingerprint or "",
            max_points=orm.max_points,
            room=Room.model_validate(orm.room),
            status=orm.status,
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
        statement = select(ScenarioORM).where(
            ScenarioORM.id == scenario_id,
            ScenarioORM.room.is_not(None),
        )
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
        statement = select(ScenarioORM).where(ScenarioORM.room.is_not(None))
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
        """List every scenario generated from a specific rule (via its snapshot)."""
        statement = select(ScenarioORM).where(
            ScenarioORM.rule_snapshot["id"].as_string() == rule_id,
            ScenarioORM.room.is_not(None),
        )
        if not include_deleted:
            statement = statement.where(ScenarioORM.deleted_at.is_(None))
        result = await session.execute(statement)
        return [self._to_scenario(orm) for orm in result.scalars()]

    async def recent_fingerprints(
        self, session: AsyncSession, tenant_id: str, limit: int = 200
    ) -> set[str]:
        """Return fingerprints of the tenant's most recent live scenarios."""
        statement = (
            select(ScenarioORM.fingerprint)
            .where(
                ScenarioORM.tenant_id == tenant_id,
                ScenarioORM.deleted_at.is_(None),
                ScenarioORM.room.is_not(None),
                ScenarioORM.fingerprint != "",
            )
            .order_by(ScenarioORM.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(statement)
        return {fingerprint for fingerprint in result.scalars()}

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
        """Soft-delete every non-deleted scenario produced by ``rule_ids``.

        The link lives in ``rule_snapshot.id``; there is no ``rule_id`` column,
        so the update matches on the JSON copy.
        """
        if not rule_ids:
            return 0
        statement = (
            update(ScenarioORM)
            .where(
                ScenarioORM.rule_snapshot["id"].as_string().in_(rule_ids),
                ScenarioORM.deleted_at.is_(None),
            )
            .values(deleted_at=_utcnow())
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount
