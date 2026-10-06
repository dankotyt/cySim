"""Async CRUD repository for LLM-structured security rules."""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import SecurityRuleORM
from ..models.document import SecurityRule


class SecurityRuleRepository:
    """Translate between :class:`SecurityRuleORM` rows and :class:`SecurityRule` DTOs."""

    @staticmethod
    def _to_orm(rule: SecurityRule, tenant_id: str) -> SecurityRuleORM:
        return SecurityRuleORM(
            id=rule.id,
            tenant_id=tenant_id,
            document_id=rule.document_id,
            title=rule.title,
            description=rule.description,
            section=rule.section,
            topic=rule.topic,
            linked_docs=list(rule.linked_docs),
            created_at=rule.created_at,
        )

    @staticmethod
    def _to_rule(orm: SecurityRuleORM) -> SecurityRule:
        return SecurityRule(
            id=orm.id,
            title=orm.title,
            description=orm.description,
            section=orm.section,
            topic=orm.topic,
            linked_docs=list(orm.linked_docs or []),
            document_id=orm.document_id,
            created_at=orm.created_at,
        )

    async def create_many(
        self, session: AsyncSession, tenant_id: str, rules: list[SecurityRule]
    ) -> list[SecurityRule]:
        """Insert several rules and return the (unchanged) DTOs."""
        for rule in rules:
            session.add(self._to_orm(rule, tenant_id))
        await session.flush()
        return rules

    async def list_by_tenant(
        self, session: AsyncSession, tenant_id: str
    ) -> list[SecurityRule]:
        """Return every rule for a tenant."""
        return await self._list(session, tenant_id)

    async def list_by_topics(
        self, session: AsyncSession, tenant_id: str, topics: list[str]
    ) -> list[SecurityRule]:
        """Return every rule whose topic is one of ``topics`` for a tenant."""
        if not topics:
            return []
        statement = select(SecurityRuleORM).where(
            SecurityRuleORM.tenant_id == tenant_id,
            SecurityRuleORM.topic.in_(topics),
        )
        result = await session.execute(statement)
        return [self._to_rule(orm) for orm in result.scalars()]

    async def list_by_filters(
        self,
        session: AsyncSession,
        tenant_id: str,
        topic: str | None = None,
        section: str | None = None,
    ) -> list[SecurityRule]:
        """Return every rule for a tenant, optionally filtered by topic/section."""
        return await self._list(session, tenant_id, topic=topic, section=section)

    async def _list(
        self,
        session: AsyncSession,
        tenant_id: str,
        topic: str | None = None,
        section: str | None = None,
    ) -> list[SecurityRule]:
        statement = select(SecurityRuleORM).where(
            SecurityRuleORM.tenant_id == tenant_id
        )
        if topic is not None:
            statement = statement.where(SecurityRuleORM.topic == topic)
        if section is not None:
            statement = statement.where(SecurityRuleORM.section == section)
        result = await session.execute(statement)
        return [self._to_rule(orm) for orm in result.scalars()]

    async def delete_by_tenant(self, session: AsyncSession, tenant_id: str) -> int:
        """Delete every rule for a tenant and return the number removed."""
        statement = delete(SecurityRuleORM).where(
            SecurityRuleORM.tenant_id == tenant_id
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount

    async def delete_by_document(self, session: AsyncSession, document_id: str) -> int:
        """Delete every rule belonging to a document and return the number removed."""
        statement = delete(SecurityRuleORM).where(
            SecurityRuleORM.document_id == document_id
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount
