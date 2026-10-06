"""Tests for the department repository."""
from app.models.department import Department
from app.repositories.department_repository import DepartmentRepository


def _department(**overrides):
    defaults = dict(
        tenant_id="acme",
        name="sales",
        allowed_topics=["phishing", "vishing"],
    )
    defaults.update(overrides)
    return Department(**defaults)


async def test_create_and_get_by_name(db_session):
    repo = DepartmentRepository()
    await repo.create(db_session, _department())

    stored = await repo.get_by_name(db_session, "acme", "sales")

    assert stored is not None
    assert stored.allowed_topics == ["phishing", "vishing"]


async def test_get_by_name_missing_returns_none(db_session):
    repo = DepartmentRepository()

    assert await repo.get_by_name(db_session, "acme", "sales") is None


async def test_list_by_tenant(db_session):
    repo = DepartmentRepository()
    await repo.create(db_session, _department(name="sales"))
    await repo.create(db_session, _department(name="hr", allowed_topics=["passwords"]))

    result = await repo.list_by_tenant(db_session, "acme")

    assert {d.name for d in result} == {"sales", "hr"}


async def test_update(db_session):
    repo = DepartmentRepository()
    created = await repo.create(db_session, _department())

    created.allowed_topics = ["passwords"]
    updated = await repo.update(db_session, created)

    assert updated is not None
    stored = await repo.get_by_name(db_session, "acme", "sales")
    assert stored.allowed_topics == ["passwords"]


async def test_delete(db_session):
    repo = DepartmentRepository()
    await repo.create(db_session, _department())

    assert await repo.delete(db_session, "acme", "sales") is True
    assert await repo.get_by_name(db_session, "acme", "sales") is None
    assert await repo.delete(db_session, "acme", "sales") is False
