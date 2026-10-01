"""Async CRUD repository for precomputed security rules."""
import hashlib

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import SecurityRuleORM
from ..models.document import SecurityRule


class SecurityRuleRepository:
    """Translate between :class:`SecurityRuleORM` rows and :class:`SecurityRule` DTOs.

    Inserts are idempotent: a rule is identified by the SHA-256 hash of its
    ``source``, ``page`` and ``description`` (scoped per tenant). The matching
    unique constraint in PostgreSQL is the final backstop.
    """

    @staticmethod
    def _content_hash(rule: SecurityRule) -> str:
        """Return a deterministic content hash for idempotent inserts."""
        payload = f"{rule.source}\n{rule.page}\n{rule.description}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_orm(rule: SecurityRule, tenant_id: str, document_id: str) -> SecurityRuleORM:
        return SecurityRuleORM(
            id=rule.id,
            tenant_id=tenant_id,
            document_id=document_id,
            title=rule.title,
            description=rule.description,
            category=rule.category,
            source=rule.source,
            page=rule.page,
            score=rule.score,
            content_hash=SecurityRuleRepository._content_hash(rule),
            created_at=rule.created_at,
        )

    @staticmethod
    def _to_rule(orm: SecurityRuleORM) -> SecurityRule:
        return SecurityRule(
            id=orm.id,
            title=orm.title,
            description=orm.description,
            category=orm.category,
            source=orm.source,
            page=orm.page,
            score=orm.score,
            created_at=orm.created_at,
        )

    async def _existing_hashes(
        self, session: AsyncSession, tenant_id: str, hashes: list[str]
    ) -> set[str]:
        """Return the subset of ``hashes`` already stored for a tenant."""
        if not hashes:
            return set()
        statement = select(SecurityRuleORM.content_hash).where(
            SecurityRuleORM.tenant_id == tenant_id,
            SecurityRuleORM.content_hash.in_(hashes),
        )
        result = await session.execute(statement)
        return set(result.scalars())

    async def create_many(
        self,
        session: AsyncSession,
        tenant_id: str,
        document_id: str,
        rules: list[SecurityRule],
    ) -> list[SecurityRule]:
        """Insert several rules idempotently and return the newly stored DTOs."""
        rule_hashes = [(rule, self._content_hash(rule)) for rule in rules]

        # Dedupe within the incoming batch (one chunk may match several queries).
        seen: set[str] = set()
        deduped: list[tuple[SecurityRule, str]] = []
        for rule, content_hash in rule_hashes:
            if content_hash in seen:
                continue
            seen.add(content_hash)
            deduped.append((rule, content_hash))

        if not deduped:
            return []

        # Skip rules already persisted for this tenant (idempotency across runs).
        existing = await self._existing_hashes(
            session, tenant_id, [content_hash for _, content_hash in deduped]
        )
        new_rules = [
            rule for rule, content_hash in deduped if content_hash not in existing
        ]

        for rule in new_rules:
            session.add(self._to_orm(rule, tenant_id, document_id))
        await session.flush()
        return new_rules

    async def list_by_tenant(
        self, session: AsyncSession, tenant_id: str
    ) -> list[SecurityRule]:
        """Return every rule for a tenant."""
        statement = select(SecurityRuleORM).where(
            SecurityRuleORM.tenant_id == tenant_id
        )
        result = await session.execute(statement)
        return [self._to_rule(orm) for orm in result.scalars()]

    async def list_by_category(
        self, session: AsyncSession, tenant_id: str, category: str
    ) -> list[SecurityRule]:
        """Return every rule of a given category for a tenant."""
        statement = select(SecurityRuleORM).where(
            SecurityRuleORM.tenant_id == tenant_id,
            SecurityRuleORM.category == category,
        )
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
