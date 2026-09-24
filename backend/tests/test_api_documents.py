"""Integration tests for the document API endpoints."""
import os
import tempfile
from pathlib import Path

# Redirect the module-level application's storage away from the repository
# before importing app.main (which builds a default app at import time).
_TEST_TMP = tempfile.mkdtemp(prefix="cybersim-test-")
os.environ.setdefault("STORAGE_DIR", os.path.join(_TEST_TMP, "uploads"))
os.environ.setdefault("CHROMA_PERSIST_DIR", os.path.join(_TEST_TMP, "chroma"))
os.environ.setdefault("QUARANTINE_DIR", os.path.join(_TEST_TMP, "quarantine"))

import chromadb  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from app.api.v1.documents import get_service  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.document import DocumentStatus  # noqa: E402
from app.services.document_service import DocumentService  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeEmbeddingProvider,
    FakeValidator,
    FailingValidator,
)


def _build_app(settings, service, db_session):
    app = create_app(settings=settings)
    app.dependency_overrides[get_service] = lambda: service

    async def override_get_db():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture
def service(settings) -> DocumentService:
    # Use a PersistentClient on the per-test tmp_path so tests are isolated;
    # chromadb's default ephemeral Client shares state across instances.
    return DocumentService(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        chroma_client=chromadb.PersistentClient(path=str(settings.chroma_persist_dir)),
        validator=FakeValidator(),
    )


@pytest.fixture
async def client(settings, service, db_session):
    app = _build_app(settings, service, db_session)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _upload_txt(client: httpx.AsyncClient, name: str, content: bytes, tenant: str = "acme") -> str:
    response = await client.post(
        "/api/v1/documents/upload",
        files={"files": (name, content, "text/plain")},
        data={"tenant_id": tenant},
    )
    assert response.status_code == 201, response.text
    return response.json()[0]["document_id"]


async def test_upload_and_get_document(client):
    document_id = await _upload_txt(client, "policy.txt", b"Passwords must be strong.")

    info = await client.get(f"/api/v1/documents/{document_id}", params={"tenant_id": "acme"})
    assert info.status_code == 200
    body = info.json()
    assert body["filename"] == "policy.txt"
    assert body["status"] == "uploaded"
    assert body["tenant_id"] == "acme"


async def test_upload_rejects_unsupported_type(client):
    response = await client.post(
        "/api/v1/documents/upload",
        files={"files": ("archive.zip", b"data", "application/zip")},
        data={"tenant_id": "acme"},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


async def test_process_and_search(client):
    document_id = await _upload_txt(
        client,
        "policy.txt",
        b"Employees must not share passwords. Suspicious attachments must be reported.",
    )

    process = await client.post(
        "/api/v1/documents/process",
        json={"document_id": document_id, "tenant_id": "acme"},
    )
    assert process.status_code == 200, process.text
    assert process.json()["status"] == "processed"
    assert process.json()["chunks_created"] >= 1

    search = await client.get(
        "/api/v1/documents/search",
        params={"q": "password sharing", "tenant_id": "acme", "top_k": 3},
    )
    assert search.status_code == 200
    results = search.json()["results"]
    assert results
    assert all(result["source"] == "policy.txt" for result in results)


async def test_search_supports_filename_filter(client):
    document_id = await _upload_txt(client, "policy.txt", b"Passwords must be strong.")

    await client.post(
        "/api/v1/documents/process",
        json={"document_id": document_id, "tenant_id": "acme"},
    )

    search = await client.get(
        "/api/v1/documents/search",
        params={"q": "passwords", "tenant_id": "acme", "filename": "other.txt"},
    )
    assert search.status_code == 200
    assert search.json()["results"] == []


async def test_delete_document(client):
    document_id = await _upload_txt(client, "policy.txt", b"Confidential data rules.")

    await client.post(
        "/api/v1/documents/process",
        json={"document_id": document_id, "tenant_id": "acme"},
    )

    deleted = await client.delete(
        f"/api/v1/documents/{document_id}", params={"tenant_id": "acme"}
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    after = await client.get(f"/api/v1/documents/{document_id}", params={"tenant_id": "acme"})
    assert after.status_code == 404


async def test_document_not_found_returns_404(client):
    response = await client.get("/api/v1/documents/missing", params={"tenant_id": "acme"})
    assert response.status_code == 404


async def test_process_quarantines_invalid_document(settings, db_session):
    service = DocumentService(
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        chroma_client=chromadb.PersistentClient(path=str(settings.chroma_persist_dir)),
        validator=FailingValidator(),
    )
    app = _build_app(settings, service, db_session)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        document_id = await _upload_txt(client, "bad.txt", b"irrelevant content")

        process = await client.post(
            "/api/v1/documents/process",
            json={"document_id": document_id, "tenant_id": "acme"},
        )
        assert process.status_code == 500

    document = await service.repository.get(db_session, document_id)
    assert document.status == DocumentStatus.FAILED
    assert document.error == "simulated validation failure"

    quarantine_path = Path(document.file_path)
    assert quarantine_path.exists()
    assert settings.quarantine_dir in quarantine_path.parents


async def test_extract_rules_returns_structured_rules(service, db_session):
    await service.upload_document(
        db_session,
        "acme",
        "rules.txt",
        b"Employees must not share passwords. Suspicious attachments must be reported.",
    )
    document_id = (await service.repository.list(db_session, "acme"))[0].id
    await service.process_document(db_session, document_id, "acme")

    rules = await service.extract_rules("acme", query="password and attachment rules", top_k=3)
    assert rules
    assert all(rule.source == "rules.txt" for rule in rules)
    assert all(rule.title for rule in rules)
    assert all(rule.page == 1 for rule in rules)
