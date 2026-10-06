"""Tests for the security rule repository."""
from sqlalchemy import select

from app.models.db_models import SecurityRuleORM
from app.models.document import SecurityRule
from app.repositories.security_rule_repository import SecurityRuleRepository


def _rule(**overrides):
    defaults = dict(
        title="Правило",
        description="Не передавать пароли.",
        section="Пароли",
        topic="phishing",
        linked_docs=[],
        document_id="doc-1",
    )
    defaults.update(overrides)
    return SecurityRule(**defaults)


async def test_create_many_and_list_by_tenant(db_session):
    repo = SecurityRuleRepository()
    rules = [
        _rule(topic="phishing", description="Не передавать пароли."),
        _rule(topic="vishing", description="Не называть код из SMS."),
    ]
    await repo.create_many(db_session, "acme", rules)

    result = await repo.list_by_tenant(db_session, "acme")

    assert len(result) == 2
    assert {rule.topic for rule in result} == {"phishing", "vishing"}
    assert all(rule.id for rule in result)
    assert all(rule.document_id == "doc-1" for rule in result)


async def test_create_many_persists_full_rule(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        [
            _rule(
                title="Сложные пароли",
                description="Пароль должен содержать 12 символов.",
                section="Управление доступом",
                topic="passwords",
                linked_docs=["Регламент доступа"],
                document_id="doc-1",
            )
        ],
    )

    rows = (await db_session.execute(select(SecurityRuleORM))).scalars().all()

    assert len(rows) == 1
    assert rows[0].section == "Управление доступом"
    assert rows[0].topic == "passwords"
    assert rows[0].linked_docs == ["Регламент доступа"]
    assert rows[0].document_id == "doc-1"


async def test_list_by_topic(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        [
            _rule(topic="phishing", description="Не открывать вложения."),
            _rule(topic="vishing", description="Не называть код из SMS."),
        ],
    )

    phishing = await repo.list_by_topic(db_session, "acme", "phishing")

    assert len(phishing) == 1
    assert phishing[0].topic == "phishing"


async def test_list_by_filters(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        [
            _rule(topic="phishing", section="Электронная почта", description="Не открывать вложения."),
            _rule(topic="phishing", section="Сеть", description="Не переходить по ссылкам."),
        ],
    )

    filtered = await repo.list_by_filters(
        db_session, "acme", topic="phishing", section="Сеть"
    )

    assert len(filtered) == 1
    assert filtered[0].section == "Сеть"


async def test_delete_by_tenant(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        [
            _rule(description="Не передавать пароли."),
            _rule(description="Не открывать вложения."),
        ],
    )

    removed = await repo.delete_by_tenant(db_session, "acme")

    assert removed == 2
    assert await repo.list_by_tenant(db_session, "acme") == []


async def test_delete_by_document(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        [_rule(document_id="doc-A", description="Не передавать пароли.")],
    )
    await repo.create_many(
        db_session,
        "acme",
        [_rule(document_id="doc-B", description="Не открывать вложения.")],
    )

    removed = await repo.delete_by_document(db_session, "doc-A")

    assert removed == 1
    remaining = await repo.list_by_tenant(db_session, "acme")
    assert len(remaining) == 1
    assert remaining[0].description == "Не открывать вложения."
