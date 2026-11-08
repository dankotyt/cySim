"""Application configuration loaded from environment variables."""
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Default tenant id used as a fallback when a request does not specify one.
DEFAULT_TENANT_ID = "default"

# Repository root (backend/app/core/config.py -> ... -> <repo>).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Central settings for the document analysis module.

    Every value can be overridden through environment variables
    (case-insensitive) or a local ``.env`` file.
    """

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
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

    # LLM backend. All inference is remote over an OpenAI-compatible HTTP API:
    # "vllm" (GPU / low-vram), "ollama" (CPU-only), "openai" (external API).
    llm_backend: Literal["ollama", "openai", "vllm"] = "vllm"
    llm_model: str = "qwen3:8b-q4_K_M"
    llm_base_url: str = "http://localhost:11434"
    llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    llm_temperature: float = 0.7
    llm_num_ctx: int = 8192
    llm_timeout: int = 120

    # vLLM: the LoRA adapter is served under its own model name.
    vllm_base_url: str = "http://localhost:18001/v1"
    vllm_lora_model: str = "secpol"

    # Ollama (CPU fallback), OpenAI-compatible endpoint.
    ollama_base_url: str = "http://localhost:11434/v1"

    # Rule extraction (the adapter itself is served by vLLM).
    lora_strict: bool = False
    lora_max_new_tokens: int = 2048
    lora_max_input_length: int = 8192

    # Chunking. Sizes are in characters (~4 characters == 1 token for English);
    # tune these to match the 500-1000 token / 100-200 token overlap guidance
    # for your language and model.
    chunk_size: int = 800
    chunk_overlap: int = 100

    # Documents
    allowed_extensions: Annotated[set[str], NoDecode] = {".pdf", ".docx", ".txt"}
    max_upload_size_mb: int = 50

    # Validation
    min_document_chars: int = 100
    min_document_chunks: int = 1

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _parse_extensions(cls, value: object) -> object:
        """Accept a comma-separated string or an existing collection."""
        if isinstance(value, str):
            items = (item.strip().lower() for item in value.split(",") if item.strip())
            return {item if item.startswith(".") else f".{item}" for item in items}
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
