"""Tests for the security rule repository."""
from sqlalchemy import select

from app.models.db_models import SecurityRuleORM
from app.models.document import SecurityRule
from app.repositories.security_rule_repository import SecurityRuleRepository


def _rule(**overrides):
    defaults = dict(
        description="Не передавать пароли.",
        topic="phishing",
        audience=["general"],
        document_id="doc-1",
    )
    defaults.update(overrides)
    return SecurityRule(**defaults)


async def test_create_many_and_list_by_tenant(db_session):
    repo = SecurityRuleRepository()
    rules = [
        _rule(topic="phishing", description="Не передавать пароли."),
        _rule(topic="internet", description="Не переходить по подозрительным ссылкам."),
    ]
    created = await repo.create_many(db_session, "acme", rules)

    assert len(created) == 2
    result = await repo.list_by_tenant(db_session, "acme")

    assert len(result) == 2
    assert {rule.topic for rule in result} == {"phishing", "internet"}
    assert all(rule.id for rule in result)
    assert all(rule.document_id == "doc-1" for rule in result)


async def test_create_many_persists_full_rule(db_session):
    repo = SecurityRuleRepository()
    [created] = await repo.create_many(
        db_session,
        "acme",
        [
            _rule(
                description="Пароль должен содержать 12 символов.",
                topic="passwords",
                audience=["it", "security"],
                document_id="doc-1",
            )
        ],
    )

    rows = (await db_session.execute(select(SecurityRuleORM))).scalars().all()

    assert len(rows) == 1
    assert rows[0].topic == "passwords"
    assert rows[0].audience == ["it", "security"]
    assert rows[0].document_id == "doc-1"
    assert rows[0].content_hash == created.content_hash
    assert rows[0].content_hash


async def test_create_many_dedups_same_text_and_topic(db_session):
    repo = SecurityRuleRepository()
    created = await repo.create_many(
        db_session,
        "acme",
        [
            _rule(description="Не передавать пароли."),
            _rule(description="  не   ПЕРЕДАВАТЬ пароли.  "),
        ],
    )

    assert len(created) == 1
    rows = (await db_session.execute(select(SecurityRuleORM))).scalars().all()
    assert len(rows) == 1


async def test_create_many_dedups_across_calls(db_session):
    repo = SecurityRuleRepository()
    first = _rule(description="Не открывать вложения.")
    second = _rule(description="Не открывать вложения.")

    assert len(await repo.create_many(db_session, "acme", [first])) == 1
    assert await repo.create_many(db_session, "acme", [second]) == []


async def test_create_many_allows_same_text_with_other_topic(db_session):
    repo = SecurityRuleRepository()
    created = await repo.create_many(
        db_session,
        "acme",
        [
            _rule(topic="phishing", description="Не передавать пароли."),
            _rule(topic="passwords", description="Не передавать пароли."),
        ],
    )

    assert len(created) == 2


async def test_list_by_topics(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        [
            _rule(topic="phishing", description="Не открывать вложения."),
            _rule(topic="internet", description="Не переходить по подозрительным ссылкам."),
        ],
    )

    phishing = await repo.list_by_topics(db_session, "acme", ["phishing"])

    assert len(phishing) == 1
    assert phishing[0].topic == "phishing"


async def test_list_by_filters(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        [
            _rule(topic="phishing", description="Не открывать вложения."),
            _rule(topic="internet", description="Не переходить по подозрительным ссылкам."),
        ],
    )

    filtered = await repo.list_by_filters(db_session, "acme", topic="phishing")

    assert len(filtered) == 1
    assert filtered[0].topic == "phishing"


async def test_list_by_filters_document_and_pagination(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        [
            _rule(document_id="doc-A", description="Не открывать вложения."),
            _rule(document_id="doc-B", description="Не переходить по ссылкам."),
            _rule(document_id="doc-B", description="Не передавать пароли."),
        ],
    )

    by_document = await repo.list_by_filters(db_session, "acme", document_id="doc-B")
    assert len(by_document) == 2

    page = await repo.list_by_filters(db_session, "acme", limit=1, offset=1)
    assert len(page) == 1


async def test_soft_delete_hides_rule(db_session):
    repo = SecurityRuleRepository()
    [rule] = await repo.create_many(db_session, "acme", [_rule()])

    assert await repo.delete(db_session, rule.id) is True

    assert await repo.get(db_session, rule.id) is None
    assert await repo.list_by_tenant(db_session, "acme") == []
    assert len(await repo.list_by_tenant(db_session, "acme", include_deleted=True)) == 1
    assert await repo.get(db_session, rule.id, include_deleted=True) is not None
    assert await repo.delete(db_session, rule.id) is False


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
    assert len(await repo.list_by_tenant(db_session, "acme", include_deleted=True)) == 2


async def test_delete_by_document(db_session):
    repo = SecurityRuleRepository()
    [doc_a_rule] = await repo.create_many(
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

    assert removed == [doc_a_rule.id]
    remaining = await repo.list_by_tenant(db_session, "acme")
    assert len(remaining) == 1
    assert remaining[0].description == "Не открывать вложения."
