"""Async CRUD repository for LLM-structured security rules."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.rule_text import rule_content_hash
from ..models.db_models import SecurityRuleORM
from ..models.document import SecurityRule


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class SecurityRuleRepository:
    """Translate between :class:`SecurityRuleORM` rows and :class:`SecurityRule` DTOs.

    Rules are de-duplicated per tenant by ``content_hash`` (a hash of the topic
    and the normalised description). Deletion is soft: rows stay available for
    analytics, but default queries hide them.
    """

    @staticmethod
    def _to_orm(rule: SecurityRule, tenant_id: str) -> SecurityRuleORM:
        return SecurityRuleORM(
            id=rule.id,
            tenant_id=tenant_id,
            document_id=rule.document_id,
            description=rule.description,
            topic=rule.topic,
            intent=rule.intent,
            audience=list(rule.audience),
            content_hash=rule.content_hash
            or rule_content_hash(rule.topic, rule.description),
            created_at=rule.created_at,
        )

    @staticmethod
    def _to_rule(orm: SecurityRuleORM) -> SecurityRule:
        return SecurityRule(
            id=orm.id,
            description=orm.description,
            topic=orm.topic,
            intent=orm.intent or "",
            audience=list(orm.audience or []),
            document_id=orm.document_id,
            content_hash=orm.content_hash,
            created_at=orm.created_at,
        )

    async def create_many(
        self, session: AsyncSession, tenant_id: str, rules: list[SecurityRule]
    ) -> list[SecurityRule]:
        """Insert rules, skipping duplicates within the batch and the tenant."""
        prepared: list[tuple[SecurityRule, str]] = []
        seen: set[str] = set()
        for rule in rules:
            content_hash = rule.content_hash or rule_content_hash(
                rule.topic, rule.description
            )
            if content_hash in seen:
                continue
            seen.add(content_hash)
            prepared.append((rule, content_hash))
        if not prepared:
            return []

        existing_statement = select(SecurityRuleORM.content_hash).where(
            SecurityRuleORM.tenant_id == tenant_id,
            SecurityRuleORM.content_hash.in_([h for _, h in prepared]),
            SecurityRuleORM.deleted_at.is_(None),
        )
        existing = set((await session.execute(existing_statement)).scalars().all())

        created: list[SecurityRule] = []
        for rule, content_hash in prepared:
            if content_hash in existing:
                continue
            orm = self._to_orm(rule, tenant_id)
            orm.content_hash = content_hash
            session.add(orm)
            created.append(rule)
            existing.add(content_hash)
        await session.flush()
        return created

    async def list_by_tenant(
        self,
        session: AsyncSession,
        tenant_id: str,
        include_deleted: bool = False,
    ) -> list[SecurityRule]:
        """Return every non-deleted rule for a tenant."""
        return await self._list(session, tenant_id, include_deleted=include_deleted)

    async def get(
        self,
        session: AsyncSession,
        rule_id: str,
        include_deleted: bool = False,
    ) -> SecurityRule | None:
        """Return a rule by id, or ``None`` when it is missing/deleted."""
        statement = select(SecurityRuleORM).where(SecurityRuleORM.id == rule_id)
        if not include_deleted:
            statement = statement.where(SecurityRuleORM.deleted_at.is_(None))
        orm = (await session.execute(statement)).scalar_one_or_none()
        return self._to_rule(orm) if orm is not None else None

    async def get_for_tenant(
        self, session: AsyncSession, rule_id: str, tenant_id: str
    ) -> SecurityRule | None:
        """Return a non-deleted rule only when it belongs to ``tenant_id``."""
        statement = select(SecurityRuleORM).where(
            SecurityRuleORM.id == rule_id,
            SecurityRuleORM.tenant_id == tenant_id,
            SecurityRuleORM.deleted_at.is_(None),
        )
        orm = (await session.execute(statement)).scalar_one_or_none()
        return self._to_rule(orm) if orm is not None else None

    async def set_classification(
        self,
        session: AsyncSession,
        rule_id: str,
        intent: str,
        topic: str | None = None,
    ) -> bool:
        """Persist the resolved intent and (optionally) the corrected topic."""
        orm = await session.get(SecurityRuleORM, rule_id)
        if orm is None:
            return False
        orm.intent = intent
        if topic:
            orm.topic = topic
        await session.flush()
        return True

    async def delete(self, session: AsyncSession, rule_id: str) -> bool:
        """Soft-delete a single rule; return ``False`` when it is unknown.

        Linked scenarios are soft-deleted by the caller, so generated content
        stays in the database for analytics.
        """
        orm = await session.get(SecurityRuleORM, rule_id)
        if orm is None or orm.deleted_at is not None:
            return False
        orm.deleted_at = _utcnow()
        await session.flush()
        return True

    async def list_by_topics(
        self, session: AsyncSession, tenant_id: str, topics: list[str]
    ) -> list[SecurityRule]:
        """Return every non-deleted rule whose topic is one of ``topics``."""
        if not topics:
            return []
        statement = select(SecurityRuleORM).where(
            SecurityRuleORM.tenant_id == tenant_id,
            SecurityRuleORM.topic.in_(topics),
            SecurityRuleORM.deleted_at.is_(None),
        )
        result = await session.execute(statement)
        return [self._to_rule(orm) for orm in result.scalars()]

    async def list_by_filters(
        self,
        session: AsyncSession,
        tenant_id: str,
        topic: str | None = None,
        document_id: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[SecurityRule]:
        """Return non-deleted rules for a tenant, optionally filtered/paged."""
        return await self._list(
            session,
            tenant_id,
            topic=topic,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

    async def _list(
        self,
        session: AsyncSession,
        tenant_id: str,
        topic: str | None = None,
        document_id: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        include_deleted: bool = False,
    ) -> list[SecurityRule]:
        statement = select(SecurityRuleORM).where(
            SecurityRuleORM.tenant_id == tenant_id
        )
        if not include_deleted:
            statement = statement.where(SecurityRuleORM.deleted_at.is_(None))
        if topic is not None:
            statement = statement.where(SecurityRuleORM.topic == topic)
        if document_id is not None:
            statement = statement.where(SecurityRuleORM.document_id == document_id)
        statement = statement.order_by(SecurityRuleORM.created_at)
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        result = await session.execute(statement)
        return [self._to_rule(orm) for orm in result.scalars()]

    async def delete_by_tenant(self, session: AsyncSession, tenant_id: str) -> int:
        """Soft-delete every rule for a tenant and return the number touched."""
        statement = (
            update(SecurityRuleORM)
            .where(
                SecurityRuleORM.tenant_id == tenant_id,
                SecurityRuleORM.deleted_at.is_(None),
            )
            .values(deleted_at=_utcnow())
        )
        result = await session.execute(statement)
        await session.flush()
        return result.rowcount

    async def delete_by_document(
        self, session: AsyncSession, document_id: str
    ) -> list[str]:
        """Soft-delete every rule of a document; return the affected rule ids."""
        ids_statement = select(SecurityRuleORM.id).where(
            SecurityRuleORM.document_id == document_id,
            SecurityRuleORM.deleted_at.is_(None),
        )
        rule_ids = list((await session.execute(ids_statement)).scalars().all())
        if rule_ids:
            statement = (
                update(SecurityRuleORM)
                .where(SecurityRuleORM.id.in_(rule_ids))
                .values(deleted_at=_utcnow())
            )
            await session.execute(statement)
            await session.flush()
        return rule_ids
