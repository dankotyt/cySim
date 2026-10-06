"""Tests for the missing-reference repository."""
from app.repositories.missing_reference_repository import MissingReferenceRepository


async def test_list_and_delete_by_tenant(db_session):
    repo = MissingReferenceRepository()
    await repo.create(db_session, "acme", "doc-1", "Регламент доступа", "Пароли")
    await repo.create(db_session, "acme", "doc-2", "Политика хранения", "Данные")
    await repo.create(db_session, "other", "doc-3", "Инструкция", "Сеть")

    acme = await repo.list_by_tenant(db_session, "acme")
    assert len(acme) == 2
    assert {r.reference for r in acme} == {"Регламент доступа", "Политика хранения"}
    assert all(r.document_id in {"doc-1", "doc-2"} for r in acme)

    removed = await repo.delete_by_tenant(db_session, "acme")
    assert removed == 2
    assert await repo.list_by_tenant(db_session, "acme") == []
    assert len(await repo.list_by_tenant(db_session, "other")) == 1
