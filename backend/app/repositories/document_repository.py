"""Async CRUD repository for document metadata."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import DocumentORM
from ..models.document import Document, DocumentStatus


class DocumentRepository:
    """Async repository translating between ORM rows and Pydantic DTOs.

    Only document metadata is persisted; the source content is never stored.
    """

    @staticmethod
    def _to_orm(document: Document) -> DocumentORM:
        """Convert a Pydantic :class:`Document` to an ORM row."""
        return DocumentORM(
            id=document.id,
            tenant_id=document.tenant_id,
            name=document.name,
            content_hash=document.content_hash,
            size_bytes=document.size_bytes,
            rule_count=document.rule_count,
            status=document.status.value,
            created_at=document.created_at,
        )

    @staticmethod
    def _to_document(orm: DocumentORM) -> Document:
        """Convert an ORM row to a Pydantic :class:`Document`."""
        return Document(
            id=orm.id,
            tenant_id=orm.tenant_id,
            name=orm.name,
            content_hash=orm.content_hash,
            size_bytes=orm.size_bytes,
            rule_count=orm.rule_count,
            status=DocumentStatus(orm.status),
            created_at=orm.created_at,
        )

    async def create(self, session: AsyncSession, document: Document) -> Document:
        """Insert a new document record and return the (unchanged) DTO."""
        session.add(self._to_orm(document))
        await session.flush()
        return document

    async def get(self, session: AsyncSession, document_id: str) -> Document | None:
        """Return a document by id, or ``None`` when it does not exist."""
        orm = await session.get(DocumentORM, document_id)
        return self._to_document(orm) if orm is not None else None

    async def update(self, session: AsyncSession, document: Document) -> Document | None:
        """Persist changes to an existing document.

        Returns ``None`` when the row no longer exists; the caller is
        responsible for surfacing a ``DocumentNotFoundError`` in that case.
        """
        orm = await session.get(DocumentORM, document.id)
        if orm is None:
            return None
        updated = self._to_orm(document)
        orm.tenant_id = updated.tenant_id
        orm.name = updated.name
        orm.content_hash = updated.content_hash
        orm.size_bytes = updated.size_bytes
        orm.rule_count = updated.rule_count
        orm.status = updated.status
        orm.created_at = updated.created_at
        await session.flush()
        return document

    async def delete(self, session: AsyncSession, document_id: str) -> None:
        """Remove a document record, ignoring a missing id."""
        orm = await session.get(DocumentORM, document_id)
        if orm is not None:
            await session.delete(orm)
            await session.flush()

    async def list(
        self, session: AsyncSession, tenant_id: str | None = None
    ) -> list[Document]:
        """List all records, optionally filtered by tenant."""
        statement = select(DocumentORM)
        if tenant_id is not None:
            statement = statement.where(DocumentORM.tenant_id == tenant_id)
        result = await session.execute(statement)
        return [self._to_document(orm) for orm in result.scalars()]
