"""Async CRUD + full-text search repository for document chunks."""
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import DocumentChunkORM
from ..models.document import Chunk


class DocumentChunkRepository:
    """Persist :class:`Chunk` records and run similarity search over them."""

    @staticmethod
    def _to_orm(chunk: Chunk, tenant_id: str) -> DocumentChunkORM:
        return DocumentChunkORM(
            id=chunk.id,
            tenant_id=tenant_id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            page=chunk.page,
            text=chunk.text,
            source=chunk.source,
            document_type=chunk.document_type.value,
        )

    async def create_many(
        self, session: AsyncSession, tenant_id: str, chunks: list[Chunk]
    ) -> list[Chunk]:
        """Insert several chunks and return the (unchanged) DTOs."""
        for chunk in chunks:
            session.add(self._to_orm(chunk, tenant_id))
        await session.flush()
        return chunks

    async def delete_by_document(
        self, session: AsyncSession, document_id: str
    ) -> int:
        """Delete every chunk belonging to a document and return the count."""
        statement = delete(DocumentChunkORM).where(
            DocumentChunkORM.document_id == document_id
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount

    async def search(
        self,
        session: AsyncSession,
        tenant_id: str,
        query: str,
        *,
        top_k: int | None,
        filename: str | None,
        document_type: str | None,
        document_id: str | None,
        min_score: float,
    ) -> list[tuple[DocumentChunkORM, float]]:
        """Return chunks ranked by ``pg_trgm`` similarity to ``query``.

        ``similarity(text, query)`` returns a score in ``[0, 1]``; rows below
        ``min_score`` are dropped. The returned tuples carry the matched row and
        its similarity score.
        """
        similarity = func.similarity(DocumentChunkORM.text, query)
        statement = (
            select(DocumentChunkORM, similarity.label("score"))
            .where(
                DocumentChunkORM.tenant_id == tenant_id,
                similarity >= min_score,
            )
            .order_by(similarity.desc())
        )
        if filename is not None:
            statement = statement.where(DocumentChunkORM.source == filename)
        if document_type is not None:
            statement = statement.where(
                DocumentChunkORM.document_type == document_type
            )
        if document_id is not None:
            statement = statement.where(
                DocumentChunkORM.document_id == document_id
            )
        if top_k is not None:
            statement = statement.limit(top_k)

        result = await session.execute(statement)
        return [(row[0], float(row[1])) for row in result]
