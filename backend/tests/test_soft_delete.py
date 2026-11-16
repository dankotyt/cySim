"""Soft-delete semantics across documents, rules and scenarios."""
import pytest

from app.models.document import Document, DocumentStatus, SecurityRule
from app.models.scenario import Room, RuleSnapshot, Scenario, max_points_for
from app.repositories.document_repository import DocumentRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.security_rule_repository import SecurityRuleRepository
from app.services.document_service import (
    DocumentNotFoundError,
    DocumentService,
)
from app.services.scenario_generation import room_fingerprint
from tests.fakes import VALID_ROOM


async def _seed(session, tenant_id="acme"):
    document = Document(
        id="doc-1",
        tenant_id=tenant_id,
        name="policy.txt",
        content_hash="hash-1",
        size_bytes=10,
        status=DocumentStatus.PROCESSED,
    )
    await DocumentRepository().create(session, document)

    rule = SecurityRule(
        description="Не открывать вложения от внешних отправителей.",
        topic="phishing",
        audience=["general"],
        document_id=document.id,
    )
    [created_rule] = await SecurityRuleRepository().create_many(
        session, tenant_id, [rule]
    )

    room = Room.model_validate({**VALID_ROOM, "topic": "phishing"})
    scenario = Scenario(
        id="sc-1",
        tenant_id=tenant_id,
        rule_snapshot=RuleSnapshot(
            id=created_rule.id,
            description=created_rule.description,
            topic=created_rule.topic,
            audience=["general"],
            document_id=document.id,
        ),
        topic="phishing",
        corpus_build_id="fx",
        fingerprint=room_fingerprint(room),
        max_points=max_points_for(room.diff),
        room=room,
    )
    await ScenarioRepository().create(session, scenario)
    return document, created_rule, scenario


async def test_delete_document_hides_rules_and_scenarios(db_session, settings):
    document, rule, scenario = await _seed(db_session)
    service = DocumentService(settings=settings, rule_structurer=object())

    result = await service.delete_document(db_session, document.id, "acme")

    assert result.deleted is True
    assert await DocumentRepository().get(db_session, document.id) is None
    assert await SecurityRuleRepository().get(db_session, rule.id) is None
    assert await ScenarioRepository().get(db_session, scenario.id) is None
    assert await DocumentRepository().list(db_session, "acme") == []
    assert await SecurityRuleRepository().list_by_tenant(db_session, "acme") == []
    assert await ScenarioRepository().list_scenarios(db_session, "acme") == []


async def test_delete_document_keeps_rows_for_analytics(db_session, settings):
    document, rule, scenario = await _seed(db_session)
    service = DocumentService(settings=settings, rule_structurer=object())

    await service.delete_document(db_session, document.id, "acme")

    assert (
        await DocumentRepository().get(db_session, document.id, include_deleted=True)
        is not None
    )
    assert (
        await SecurityRuleRepository().get(db_session, rule.id, include_deleted=True)
        is not None
    )
    assert (
        await ScenarioRepository().get(db_session, scenario.id, include_deleted=True)
        is not None
    )
    assert len(
        await DocumentRepository().list(db_session, "acme", include_deleted=True)
    ) == 1


async def test_delete_document_rejects_foreign_tenant(db_session, settings):
    document, _, _ = await _seed(db_session, tenant_id="acme")
    service = DocumentService(settings=settings, rule_structurer=object())

    with pytest.raises(DocumentNotFoundError):
        await service.delete_document(db_session, document.id, "other")
