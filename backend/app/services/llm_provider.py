"""LLM backends for scenario generation (Ollama + OpenAI-compatible APIs)."""
from abc import ABC, abstractmethod
from typing import Any

from ..core.config import Settings
from ..core.logging import get_logger

logger = get_logger(__name__)


class LLMProvider(ABC):
    """Abstract interface for text-generation backends."""

    name: str = "base"

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion for ``prompt`` and return the raw text."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return ``True`` when the backend is reachable."""


class OllamaLLMProvider(LLMProvider):
    """Generation backend backed by a local Ollama instance (Qwen 3)."""

    name = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str,
        temperature: float = 0.7,
        num_ctx: int = 8192,
        timeout: int = 120,
    ) -> None:
        import ollama  # local import to keep the OpenAI path dependency-free

        self.model = model
        self._client = ollama.Client(host=base_url, timeout=timeout)
        self._temperature = temperature
        self._num_ctx = num_ctx

    def generate(self, prompt: str, **kwargs: Any) -> str:
        system = kwargs.pop("system", None)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat(
            model=self.model,
            messages=messages,
            options={
                "temperature": self._temperature,
                "num_ctx": self._num_ctx,
            },
        )
        return response["message"]["content"]

    def is_available(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception as exc:  # noqa: BLE001 - availability check must not raise
            logger.warning("Ollama LLM backend unavailable: %s", exc)
            return False


class OpenAICompatibleProvider(LLMProvider):
    """Generation backend for OpenAI-compatible APIs (DeepSeek, YandexGPT, GigaChat)."""

    name = "openai"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        temperature: float = 0.7,
        timeout: int = 120,
    ) -> None:
        import httpx  # local import (already a transitive dependency of `ollama`)

        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._temperature = temperature
        self._timeout = timeout
        self._httpx = httpx

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def generate(self, prompt: str, **kwargs: Any) -> str:
        system = kwargs.pop("system", None)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self._temperature,
        }
        with self._httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    def is_available(self) -> bool:
        try:
            with self._httpx.Client(timeout=self._timeout) as client:
                response = client.get(
                    f"{self.base_url}/models", headers=self._headers()
                )
                return response.status_code == 200
        except Exception as exc:  # noqa: BLE001 - availability check must not raise
            logger.warning("OpenAI-compatible LLM backend unavailable: %s", exc)
            return False


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Return the configured generation backend."""
    provider_name = settings.llm_provider.lower()
    if provider_name == "ollama":
        return OllamaLLMProvider(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            num_ctx=settings.llm_num_ctx,
            timeout=settings.llm_timeout,
        )
    if provider_name == "openai":
        return OpenAICompatibleProvider(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
        )
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider!r}")
