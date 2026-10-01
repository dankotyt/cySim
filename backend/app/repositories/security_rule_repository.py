"""Async CRUD repository for precomputed security rules."""
import hashlib

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import SecurityRuleORM
from ..models.document import SecurityRule


class SecurityRuleRepository:
    """Translate between :class:`SecurityRuleORM` rows and :class:`SecurityRule` DTOs.

    Inserts are idempotent per ``(content_hash, attack_type)`` within a tenant:
    the same chunk may be stored once per attack type, while duplicates within a
    single attack type are skipped by content hash. The matching unique
    constraint in PostgreSQL is the final backstop.
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
            attack_type=rule.attack_type,
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
            attack_type=orm.attack_type,
            source=orm.source,
            page=orm.page,
            score=orm.score,
            created_at=orm.created_at,
        )

    async def _existing_pairs(
        self, session: AsyncSession, tenant_id: str, pairs: list[tuple[str, str]]
    ) -> set[tuple[str, str]]:
        """Return the ``(content_hash, attack_type)`` pairs already stored for a tenant."""
        if not pairs:
            return set()
        hashes = {content_hash for content_hash, _ in pairs}
        statement = select(
            SecurityRuleORM.content_hash, SecurityRuleORM.attack_type
        ).where(
            SecurityRuleORM.tenant_id == tenant_id,
            SecurityRuleORM.content_hash.in_(hashes),
        )
        result = await session.execute(statement)
        return {
            (content_hash, attack_type)
            for content_hash, attack_type in result.all()
        }

    async def create_many(
        self,
        session: AsyncSession,
        tenant_id: str,
        document_id: str,
        rules: list[SecurityRule],
    ) -> list[SecurityRule]:
        """Insert several rules idempotently and return the newly stored DTOs.

        A rule is identified by ``(content_hash, attack_type)``; the same chunk
        may therefore be stored once per attack type, while duplicates within a
        single attack type are skipped.
        """
        entries = [
            (rule, self._content_hash(rule), rule.attack_type) for rule in rules
        ]

        seen: set[tuple[str, str]] = set()
        deduped: list[tuple[SecurityRule, str, str]] = []
        for rule, content_hash, attack_type in entries:
            key = (content_hash, attack_type)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((rule, content_hash, attack_type))

        if not deduped:
            return []

        existing = await self._existing_pairs(
            session,
            tenant_id,
            [(content_hash, attack_type) for _, content_hash, attack_type in deduped],
        )
        new_rules = [
            rule
            for rule, content_hash, attack_type in deduped
            if (content_hash, attack_type) not in existing
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

    async def list_by_attack_type(
        self, session: AsyncSession, tenant_id: str, attack_type: str
    ) -> list[SecurityRule]:
        """Return every rule of an attack type for a tenant, best score first."""
        statement = (
            select(SecurityRuleORM)
            .where(
                SecurityRuleORM.tenant_id == tenant_id,
                SecurityRuleORM.attack_type == attack_type,
            )
            .order_by(SecurityRuleORM.score.desc())
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
