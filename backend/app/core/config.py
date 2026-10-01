"""Application configuration loaded from environment variables."""
from functools import lru_cache
from pathlib import Path

from typing import Annotated, Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode


class Settings(BaseSettings):
    """Central settings for the document analysis module.

    Every value can be overridden through environment variables
    (case-insensitive) or a local ``.env`` file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "CyberSim Document Analysis"
    environment: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://cybersim:changeme@localhost:5432/cybersim"

    # Storage
    storage_dir: Path = Path("data/uploads")
    chroma_persist_dir: Path = Path("data/chroma")
    quarantine_dir: Path = Path("data/quarantine")

    # Chroma server (used instead of PersistentClient when enabled)
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    use_chroma_server: bool = False

    # Embeddings
    embedding_provider: str = "ollama"  # "ollama" | "sentence-transformers"
    embedding_model: str = "bge-m3"
    ollama_base_url: str = "http://localhost:11434"
    sentence_transformer_model: str = "BAAI/bge-m3"
    embedding_batch_size: int = 32

    # LLM (scenario generation)
    llm_provider: Literal["ollama", "openai"] = "ollama"
    llm_model: str = "qwen3:8b-q4_K_M"
    llm_base_url: str = "http://localhost:11434"
    llm_api_key: str | None = None
    llm_temperature: float = 0.7
    llm_num_ctx: int = 8192
    llm_timeout: int = 120

    # Chunking. Sizes are in characters (~4 characters == 1 token for English);
    # tune these to match the 500-1000 token / 100-200 token overlap guidance
    # for your language and model.
    chunk_size: int = 800
    chunk_overlap: int = 100

    # Semantic chunking (LangChain SemanticChunker). When disabled, or when the
    # semantic splitter fails, chunk_document falls back to
    # RecursiveCharacterTextSplitter with the chunk_size/chunk_overlap above.
    semantic_chunking_enabled: bool = True
    semantic_breakpoint_type: Literal["percentile", "standard_deviation", "interquartile", "gradient"] = "percentile"
    semantic_breakpoint_amount: int = 95

    # Documents
    allowed_extensions: Annotated[set[str], NoDecode] = {".pdf", ".docx", ".txt"}
    max_upload_size_mb: int = 50
    default_tenant_id: str = "default"
    collection_prefix: str = "cybersim"

    # Validation
    min_document_chars: int = 100
    min_document_chunks: int = 1
    relevance_threshold: float = 0.5

    # Search
    min_search_score: float = 0.5

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _parse_extensions(cls, value: object) -> object:
        """Accept a comma-separated string or an existing collection."""
        if isinstance(value, str):
            items = (item.strip().lower() for item in value.split(",") if item.strip())
            return {item if item.startswith(".") else f".{item}" for item in items}
        return value

    def ensure_directories(self) -> None:
        """Create the storage, Chroma and quarantine directories on demand."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
