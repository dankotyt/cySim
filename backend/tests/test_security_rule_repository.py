"""Tests for the security rule repository and rule splitting."""
from sqlalchemy import select

from app.models.db_models import SecurityRuleORM
from app.models.document import SecurityRule
from app.repositories.security_rule_repository import SecurityRuleRepository
from app.services.document_service import _split_rule_text, _split_rules


def _rule(**overrides):
    defaults = dict(
        title="Правило",
        description="Не передавать пароли.",
        attack_type="phishing",
        source="policy.txt",
        page=1,
        score=0.9,
    )
    defaults.update(overrides)
    return SecurityRule(**defaults)


async def test_create_many_and_list_by_tenant(db_session):
    repo = SecurityRuleRepository()
    rules = [
        _rule(attack_type="phishing", description="Не передавать пароли."),
        _rule(attack_type="vishing", description="Не называть код из SMS."),
    ]
    await repo.create_many(db_session, "acme", "doc-1", rules)

    result = await repo.list_by_tenant(db_session, "acme")

    assert len(result) == 2
    assert {rule.attack_type for rule in result} == {"phishing", "vishing"}
    assert all(rule.id for rule in result)
    assert all(rule.created_at for rule in result)


async def test_create_many_sets_document_id(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(db_session, "acme", "doc-1", [_rule()])

    rows = (await db_session.execute(select(SecurityRuleORM))).scalars().all()

    assert len(rows) == 1
    assert rows[0].document_id == "doc-1"
    assert rows[0].attack_type == "phishing"


async def test_list_by_attack_type(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        "doc-1",
        [
            _rule(attack_type="phishing", description="Не открывать вложения."),
            _rule(attack_type="vishing", description="Не называть код из SMS."),
        ],
    )

    phishing = await repo.list_by_attack_type(db_session, "acme", "phishing")

    assert len(phishing) == 1
    assert phishing[0].attack_type == "phishing"


async def test_list_by_attack_type_orders_by_score(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        "doc-1",
        [
            _rule(attack_type="phishing", description="Правило A", score=0.5),
            _rule(attack_type="phishing", description="Правило B", score=0.9),
            _rule(attack_type="phishing", description="Правило C", score=0.7),
        ],
    )

    result = await repo.list_by_attack_type(db_session, "acme", "phishing")

    assert [rule.score for rule in result] == [0.9, 0.7, 0.5]


async def test_create_many_stores_chunk_per_attack_type(db_session):
    repo = SecurityRuleRepository()
    same_text = "Не передавать пароли."
    await repo.create_many(
        db_session,
        "acme",
        "doc-1",
        [
            _rule(attack_type="phishing", description=same_text),
            _rule(attack_type="vishing", description=same_text),
        ],
    )

    result = await repo.list_by_tenant(db_session, "acme")

    assert len(result) == 2
    assert {rule.attack_type for rule in result} == {"phishing", "vishing"}


async def test_create_many_dedupes_within_same_attack_type(db_session):
    repo = SecurityRuleRepository()
    rule = _rule(attack_type="phishing", description="Не передавать пароли.")

    inserted = await repo.create_many(db_session, "acme", "doc-1", [rule, rule])

    assert len(inserted) == 1
    assert len(await repo.list_by_tenant(db_session, "acme")) == 1


async def test_delete_by_tenant(db_session):
    repo = SecurityRuleRepository()
    await repo.create_many(
        db_session,
        "acme",
        "doc-1",
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
        db_session, "acme", "doc-A", [_rule(description="Не передавать пароли.")]
    )
    await repo.create_many(
        db_session, "acme", "doc-B", [_rule(description="Не открывать вложения.")]
    )

    removed = await repo.delete_by_document(db_session, "doc-A")

    assert removed == 1
    remaining = await repo.list_by_tenant(db_session, "acme")
    assert len(remaining) == 1
    assert remaining[0].description == "Не открывать вложения."


async def test_create_many_is_idempotent(db_session):
    repo = SecurityRuleRepository()
    rules = [
        _rule(description="Не передавать пароли."),
        _rule(description="Не открывать вложения."),
    ]

    first = await repo.create_many(db_session, "acme", "doc-1", rules)
    second = await repo.create_many(db_session, "acme", "doc-1", rules)

    assert len(first) == 2
    assert second == []  # duplicates skipped
    assert len(await repo.list_by_tenant(db_session, "acme")) == 2


def test_split_rule_text_numbered_and_bullets():
    text = "1. Не передавать пароли\n2. Сообщать о фишинге\n- Использовать VPN"

    assert _split_rule_text(text) == [
        "Не передавать пароли",
        "Сообщать о фишинге",
        "Использовать VPN",
    ]


def test_split_rule_text_single_rule_unchanged():
    text = "Запрещено передавать учётные данные третьим лицам."

    assert _split_rule_text(text) == [text]


def test_split_rules_expands_multi_rule_chunk():
    rule = SecurityRule(
        title="Правила",
        description="1. Не передавать пароли\n2. Сообщать о фишинге",
        attack_type="phishing",
        source="policy.txt",
        page=1,
        score=0.9,
    )

    expanded = _split_rules([rule])

    assert len(expanded) == 2
    assert expanded[0].description == "Не передавать пароли"
    assert expanded[1].description == "Сообщать о фишинге"
    assert all(rule.id for rule in expanded)
    assert all(rule.attack_type == "phishing" for rule in expanded)
