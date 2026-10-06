"""FastAPI endpoints for document upload, processing, retrieval and search."""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...models.document import (
    DeleteResponse,
    Document,
    DocumentType,
    MissingReference,
    MissingReferencesClearResponse,
    ProcessRequest,
    ProcessResponse,
    SearchResponse,
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
    """Upload one or more documents and register them for processing."""
    responses: list[UploadResponse] = []
    for file in files:
        content = await file.read()
        responses.append(
            await service.upload_document(session, tenant_id, file.filename or "unnamed", content)
        )
    return responses


@router.post("/process", response_model=ProcessResponse)
async def process_document(
    request: ProcessRequest,
    session: AsyncSession = Depends(get_db),
    service: DocumentService = Depends(get_service),
) -> ProcessResponse:
    """Parse, validate, chunk, embed and store a previously uploaded document."""
    return await service.process_document(session, request.document_id, request.tenant_id)


@router.get("/search", response_model=SearchResponse)
async def search_documents(
    q: str,
    tenant_id: str = "default",
    top_k: int = Query(5, ge=1, le=100),
    filename: str | None = None,
    document_type: DocumentType | None = None,
    min_score: float | None = Query(None, ge=0, le=1),
    service: DocumentService = Depends(get_service),
) -> SearchResponse:
    """Semantic search across a tenant's vector store."""
    return await service.search(
        query=q,
        tenant_id=tenant_id,
        top_k=top_k,
        filename=filename,
        document_type=document_type,
        min_score=min_score,
    )


@router.get("/missing-references", response_model=list[MissingReference])
async def list_missing_references(
    tenant_id: str = "default",
    session: AsyncSession = Depends(get_db),
    service: DocumentService = Depends(get_service),
) -> list[MissingReference]:
    """List internal documents referenced by rules but not yet uploaded."""
    return await service.list_missing_references(session, tenant_id)


@router.delete(
    "/missing-references", response_model=MissingReferencesClearResponse
)
async def clear_missing_references(
    tenant_id: str = "default",
    session: AsyncSession = Depends(get_db),
    service: DocumentService = Depends(get_service),
) -> MissingReferencesClearResponse:
    """Remove every missing-reference record for a tenant."""
    deleted = await service.clear_missing_references(session, tenant_id)
    return MissingReferencesClearResponse(deleted=deleted)


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
    """Delete a document and all of its embeddings."""
    return await service.delete_document(session, document_id, tenant_id)
