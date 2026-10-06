"""Repository for internal documents referenced by rules but not yet uploaded."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import MissingReferenceORM
from ..models.document import MissingReference


class MissingReferenceRepository:
    """Persist and query references to missing internal documents."""

    @staticmethod
    def _to_orm(
        tenant_id: str, document_id: str, reference: str, section: str
    ) -> MissingReferenceORM:
        return MissingReferenceORM(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            document_id=document_id,
            reference=reference,
            section=section,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _to_reference(orm: MissingReferenceORM) -> MissingReference:
        return MissingReference(
            id=orm.id,
            tenant_id=orm.tenant_id,
            document_id=orm.document_id,
            reference=orm.reference,
            section=orm.section,
            created_at=orm.created_at,
        )

    async def create(
        self,
        session: AsyncSession,
        tenant_id: str,
        document_id: str,
        reference: str,
        section: str,
    ) -> None:
        """Record one missing internal document reference."""
        session.add(self._to_orm(tenant_id, document_id, reference, section))
        await session.flush()

    async def list_by_document(
        self, session: AsyncSession, document_id: str
    ) -> list[dict]:
        """Return ``{reference, section}`` rows for a document."""
        statement = select(MissingReferenceORM).where(
            MissingReferenceORM.document_id == document_id
        )
        result = await session.execute(statement)
        return [
            {"reference": orm.reference, "section": orm.section}
            for orm in result.scalars()
        ]

    async def list_by_tenant(
        self, session: AsyncSession, tenant_id: str
    ) -> list[MissingReference]:
        """Return every missing reference for a tenant."""
        statement = select(MissingReferenceORM).where(
            MissingReferenceORM.tenant_id == tenant_id
        )
        result = await session.execute(statement)
        return [self._to_reference(orm) for orm in result.scalars()]

    async def delete_by_document(
        self, session: AsyncSession, document_id: str
    ) -> int:
        """Delete every reference for a document and return the number removed."""
        statement = delete(MissingReferenceORM).where(
            MissingReferenceORM.document_id == document_id
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount

    async def delete_by_tenant(
        self, session: AsyncSession, tenant_id: str
    ) -> int:
        """Delete every reference for a tenant and return the number removed."""
        statement = delete(MissingReferenceORM).where(
            MissingReferenceORM.tenant_id == tenant_id
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount
