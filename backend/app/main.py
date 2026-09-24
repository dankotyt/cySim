"""FastAPI application entry point for the CyberSim document analysis module."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.documents import router as documents_router
from app.core.config import Settings, get_settings
from app.core.database import get_database
from app.core.logging import configure_logging
from app.services.document_service import (
    DocumentNotFoundError,
    DocumentServiceError,
    ProcessingError,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Close the async database engine on application shutdown."""
    yield
    await get_database().dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    settings.ensure_directories()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Document analysis (RAG) module for CyberSim: ingest security "
        "documents and retrieve relevant rules via vector search.",
        lifespan=lifespan,
    )

    app.include_router(documents_router)

    @app.exception_handler(DocumentNotFoundError)
    async def handle_not_found(request: Request, exc: DocumentNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ProcessingError)
    async def handle_processing_error(request: Request, exc: ProcessingError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(DocumentServiceError)
    async def handle_service_error(request: Request, exc: DocumentServiceError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
