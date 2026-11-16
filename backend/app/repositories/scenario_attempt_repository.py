"""Async CRUD repository for scenario attempts (event logs)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import ScenarioAttemptORM
from ..models.scenario import Attempt, AttemptEvent


class ScenarioAttemptRepository:
    """Persist attempt event logs and their denormalised outcome."""

    @staticmethod
    def _to_orm(attempt: Attempt) -> ScenarioAttemptORM:
        return ScenarioAttemptORM(
            id=attempt.id,
            tenant_id=attempt.tenant_id,
            scenario_id=attempt.scenario_id,
            employee_id=attempt.employee_id,
            events=[event.model_dump(mode="json") for event in attempt.events],
            outcome=attempt.outcome,
            score=attempt.score,
            max_points=attempt.max_points,
            lessons=list(attempt.lessons),
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
        )

    @staticmethod
    def _to_attempt(orm: ScenarioAttemptORM) -> Attempt:
        return Attempt(
            id=orm.id,
            tenant_id=orm.tenant_id,
            scenario_id=orm.scenario_id,
            employee_id=orm.employee_id,
            events=[
                AttemptEvent.model_validate(event) for event in orm.events or []
            ],
            outcome=orm.outcome,
            score=orm.score,
            max_points=orm.max_points,
            lessons=list(orm.lessons or []),
            started_at=orm.started_at,
            finished_at=orm.finished_at,
        )

    async def create(self, session: AsyncSession, attempt: Attempt) -> Attempt:
        """Insert a new attempt and return the DTO."""
        session.add(self._to_orm(attempt))
        await session.flush()
        return attempt

    async def update(self, session: AsyncSession, attempt: Attempt) -> Attempt:
        """Persist the mutable fields of an attempt (log, outcome, score)."""
        orm = await session.get(ScenarioAttemptORM, attempt.id)
        if orm is None:
            return attempt
        orm.events = [event.model_dump(mode="json") for event in attempt.events]
        orm.outcome = attempt.outcome
        orm.score = attempt.score
        orm.lessons = list(attempt.lessons)
        orm.finished_at = attempt.finished_at
        await session.flush()
        return attempt

    async def get(self, session: AsyncSession, attempt_id: str) -> Attempt | None:
        """Return an attempt by id."""
        orm = await session.get(ScenarioAttemptORM, attempt_id)
        return self._to_attempt(orm) if orm is not None else None

    async def list_attempts(
        self,
        session: AsyncSession,
        tenant_id: str,
        employee_id: str | None = None,
        scenario_id: str | None = None,
    ) -> list[Attempt]:
        """List attempts for a tenant, optionally narrowed to one employee."""
        statement = select(ScenarioAttemptORM).where(
            ScenarioAttemptORM.tenant_id == tenant_id
        )
        if employee_id is not None:
            statement = statement.where(
                ScenarioAttemptORM.employee_id == employee_id
            )
        if scenario_id is not None:
            statement = statement.where(
                ScenarioAttemptORM.scenario_id == scenario_id
            )
        statement = statement.order_by(ScenarioAttemptORM.started_at)
        result = await session.execute(statement)
        return [self._to_attempt(orm) for orm in result.scalars()]
