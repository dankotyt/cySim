"""LoRAProvider — async wrapper around local Qwen2.5 + PEFT adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ...core.logging import get_logger
from ..llm_provider import LLMProvider

logger = get_logger(__name__)


class LoRAProvider(LLMProvider):
    """Async ``LLMProvider`` backed by a local Qwen2.5-7B + PEFT LoRA adapter.

    Implements ``generate(prompt, system=...) -> str`` so it plugs into any
    service that already depends on :class:`LLMProvider` (including
    ``SessionManager``). Inference is CPU/GPU blocking; calls are offloaded
    to a thread via ``asyncio.to_thread``.

    Model is loaded lazily on first ``generate`` call so importing this module
    does not require torch/peft to be installed or the weights to be present.
    """

    name = "lora"

    def __init__(
        self,
        base_model_path: str | Path,
        adapter_path: str | Path,
        max_new_tokens: int = 2048,
        max_input_length: int = 8192,
        load_in_4bit: bool = True,
        device_map: str | None = None,
    ) -> None:
        self._base_path = str(base_model_path)
        self._adapter_path = str(adapter_path)
        self._max_new_tokens = max_new_tokens
        self._max_input_length = max_input_length
        self._load_in_4bit = load_in_4bit
        self._device_map = device_map or "auto"
        self._model = None
        self._tokenizer = None
        self._load_lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is not None:
                return
            await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> None:
        import torch
        from peft import PeftModel
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )

        if not Path(self._base_path).exists():
            raise FileNotFoundError(f"Base model not found: {self._base_path}")
        if not Path(self._adapter_path).exists():
            raise FileNotFoundError(f"LoRA adapter not found: {self._adapter_path}")

        logger.info(
            "Loading LoRA base=%s adapter=%s",
            self._base_path,
            self._adapter_path,
        )
        # Prefer the adapter's tokenizer (it may carry the chat template the
        # adapter was trained with); fall back to the base model's tokenizer.
        tokenizer_path = (
            self._adapter_path
            if (Path(self._adapter_path) / "tokenizer_config.json").exists()
            else self._base_path
        )
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        kwargs: dict[str, Any] = {"device_map": self._device_map}
        if self._load_in_4bit:
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.float16,
            )
        base = AutoModelForCausalLM.from_pretrained(self._base_path, **kwargs)
        model = PeftModel.from_pretrained(base, self._adapter_path)
        model.eval()

        self._tokenizer = tokenizer
        self._model = model

    def _generate_sync(self, prompt: str, system: str | None) -> str:
        import torch

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self._max_input_length,
        ).to(self._model.device)
        with torch.no_grad():
            out = self._model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                do_sample=False,
                repetition_penalty=1.1,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        gen = out[0][inputs["input_ids"].shape[1]:]
        return self._tokenizer.decode(gen, skip_special_tokens=True).strip()

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        await self._ensure_loaded()
        system = kwargs.pop("system", None)
        return await asyncio.to_thread(self._generate_sync, prompt, system)

    async def is_available(self) -> bool:
        return (
            Path(self._base_path).exists()
            and Path(self._adapter_path).exists()
        )
