"""Pytest fixtures shared across test modules."""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import Base
from app.models import db_models  # noqa: F401 — register ORM models on Base


@pytest.fixture
def settings(tmp_path) -> Settings:
    """A Settings instance scoped to a temporary directory."""
    return Settings(
        storage_dir=tmp_path / "uploads",
        chroma_persist_dir=tmp_path / "chroma",
        quarantine_dir=tmp_path / "quarantine",
        embedding_provider="ollama",
        chunk_size=800,
        chunk_overlap=100,
        min_document_chars=10,
        min_document_chunks=1,
        relevance_threshold=0.0,
    )


@pytest.fixture
async def db_session(tmp_path):
    """A transactional async session backed by an isolated SQLite database."""
    db_path = (tmp_path / "test.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
