"""LoRA-based rule extraction from document chunks.

The adapter is served by vLLM over an OpenAI-compatible HTTP API; this
package turns document chunks into structured
:class:`~app.models.document.SecurityRule` objects.
"""
from .structurer import LoRARuleStructurer, StructureResult

__all__ = ["LoRARuleStructurer", "StructureResult"]
