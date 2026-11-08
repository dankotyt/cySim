"""LoRA-based rule extraction from document chunks.

Uses a local Qwen2.5-7B-Instruct-GPTQ-Int4 + PEFT LoRA adapter (4-bit) to turn document chunks
into structured :class:`~app.models.document.SecurityRule` objects.
"""
from .structurer import LoRARuleStructurer, StructureResult

__all__ = ["LoRARuleStructurer", "StructureResult"]
