"""Async CRUD repository for departments."""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import DepartmentORM
from ..models.department import Department


class DepartmentRepository:
    """Translate between :class:`DepartmentORM` rows and :class:`Department` DTOs."""

    @staticmethod
    def _to_orm(department: Department) -> DepartmentORM:
        return DepartmentORM(
            id=department.id,
            tenant_id=department.tenant_id,
            name=department.name,
            allowed_topics=list(department.allowed_topics),
            created_at=department.created_at,
        )

    @staticmethod
    def _to_department(orm: DepartmentORM) -> Department:
        return Department(
            id=orm.id,
            tenant_id=orm.tenant_id,
            name=orm.name,
            allowed_topics=list(orm.allowed_topics or []),
            created_at=orm.created_at,
        )

    async def create(
        self, session: AsyncSession, department: Department
    ) -> Department:
        """Insert a new department and return the (unchanged) DTO."""
        session.add(self._to_orm(department))
        await session.flush()
        return department

    async def get_by_name(
        self, session: AsyncSession, tenant_id: str, name: str
    ) -> Department | None:
        """Return a department by its (tenant-scoped) name, or ``None``."""
        statement = select(DepartmentORM).where(
            DepartmentORM.tenant_id == tenant_id,
            DepartmentORM.name == name,
        )
        result = await session.execute(statement)
        orm = result.scalar_one_or_none()
        return self._to_department(orm) if orm is not None else None

    async def list_by_tenant(
        self, session: AsyncSession, tenant_id: str
    ) -> list[Department]:
        """Return every department for a tenant."""
        statement = select(DepartmentORM).where(
            DepartmentORM.tenant_id == tenant_id
        )
        result = await session.execute(statement)
        return [self._to_department(orm) for orm in result.scalars()]

    async def update(
        self, session: AsyncSession, department: Department
    ) -> Department | None:
        """Persist changes to an existing department.

        Returns ``None`` when the id is unknown; the caller is responsible for
        surfacing a not-found error in that case.
        """
        orm = await session.get(DepartmentORM, department.id)
        if orm is None:
            return None
        orm.name = department.name
        orm.allowed_topics = list(department.allowed_topics)
        await session.flush()
        return department

    async def delete(
        self, session: AsyncSession, tenant_id: str, name: str
    ) -> bool:
        """Remove a department by its (tenant-scoped) name."""
        statement = delete(DepartmentORM).where(
            DepartmentORM.tenant_id == tenant_id,
            DepartmentORM.name == name,
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount > 0
