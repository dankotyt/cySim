"""Async LLM backends (vLLM, Ollama, OpenAI-compatible HTTP APIs)."""
from abc import ABC, abstractmethod
from typing import Any

from ..core.config import Settings
from ..core.logging import get_logger

logger = get_logger(__name__)


class LLMProvider(ABC):
    """Abstract interface for text-generation backends."""

    name: str = "base"

    @abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion for ``prompt`` and return the raw text."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return ``True`` when the backend is reachable."""


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

    def _payload_model(self) -> str:
        """Model name sent in the request payload."""
        return self.model

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        system = kwargs.pop("system", None)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._payload_model(),
            "messages": messages,
            "temperature": self._temperature,
        }
        async with self._httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    async def is_available(self) -> bool:
        try:
            async with self._httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self.base_url}/models", headers=self._headers()
                )
                return response.status_code == 200
        except Exception as exc:  # noqa: BLE001 - availability check must not raise
            logger.warning("OpenAI-compatible LLM backend unavailable: %s", exc)
            return False


class VLLMProvider(OpenAICompatibleProvider):
    """vLLM backend serving a LoRA adapter under its own model name.

    vLLM routes ``"model": "<lora name>"`` to the loaded adapter, so the
    payload's model field carries :attr:`lora_model_name` instead of a base
    model id.
    """

    name = "vllm"

    def __init__(
        self,
        base_url: str,
        lora_model_name: str = "secpol",
        api_key: str | None = None,
        temperature: float = 0.7,
        timeout: int = 120,
        max_attempts: int = 4,
        retry_base_delay: float = 1.0,
    ) -> None:
        super().__init__(
            model="",
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
        )
        self.lora_model_name = lora_model_name
        self._max_attempts = max_attempts
        self._retry_base_delay = retry_base_delay

    def _payload_model(self) -> str:
        return self.lora_model_name

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate with retries while vLLM is still starting up (connect only)."""
        import asyncio

        import httpx

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await super().generate(prompt, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == self._max_attempts:
                    raise
                delay = self._retry_base_delay * 2 ** (attempt - 1)
                logger.warning(
                    "vLLM not ready, retry %d/%d in %.1fs: %s",
                    attempt,
                    self._max_attempts,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")  # pragma: no cover


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Return the configured generation backend (all backends are HTTP-based)."""
    backend = settings.llm_backend.lower()
    if backend == "vllm":
        return VLLMProvider(
            base_url=settings.vllm_base_url,
            lora_model_name=settings.vllm_lora_model,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
        )
    if backend == "ollama":
        return OpenAICompatibleProvider(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
        )
    if backend == "openai":
        return OpenAICompatibleProvider(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
        )
    raise ValueError(f"unknown llm_backend: {settings.llm_backend}")
