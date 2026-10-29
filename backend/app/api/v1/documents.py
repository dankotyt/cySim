"""FastAPI endpoints for document upload and metadata retrieval."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...models.document import (
    DeleteResponse,
    Document,
    UploadResponse,
)
from ...services.document_service import DocumentService, get_document_service

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def get_service() -> DocumentService:
    """FastAPI dependency returning the document-service singleton."""
    return get_document_service()


@router.post("/upload", response_model=list[UploadResponse], status_code=201)
async def upload_documents(
    files: list[UploadFile] = File(...),
    tenant_id: str = Form("default"),
    session: AsyncSession = Depends(get_db),
    service: DocumentService = Depends(get_service),
) -> list[UploadResponse]:
    """Upload documents: parse, extract rules via LoRA and store metadata."""
    responses: list[UploadResponse] = []
    for file in files:
        content = await file.read()
        responses.append(
            await service.upload_document(
                session, tenant_id, file.filename or "unnamed", content
            )
        )
    return responses


@router.get("/{document_id}", response_model=Document)
async def get_document(
    document_id: str,
    tenant_id: str = "default",
    session: AsyncSession = Depends(get_db),
    service: DocumentService = Depends(get_service),
) -> Document:
    """Retrieve metadata for a single document."""
    return await service.get_document(session, document_id, tenant_id)


@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_document(
    document_id: str,
    tenant_id: str = "default",
    session: AsyncSession = Depends(get_db),
    service: DocumentService = Depends(get_service),
) -> DeleteResponse:
    """Delete a document's metadata and its derived rules."""
    return await service.delete_document(session, document_id, tenant_id)
