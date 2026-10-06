"""Shared LLM session management with approximate context budgeting."""
from ..core.logging import get_logger
from .llm_provider import LLMProvider

logger = get_logger(__name__)


class SessionManager:
    """Track approximate token usage across LLM calls and reset when full.

    The underlying :class:`LLMProvider` is stateless per call; this class adds a
    logical "session" by accumulating the estimated token count of every prompt
    and response, and starting a fresh session once the configured threshold is
    exceeded. A fresh session re-injects an ``anchor`` (a list of values to keep
    consistent across sessions) into its system prompt.

    Token counts are approximate (``len(text) / 3.5`` for Russian). The precise
    Ollama counters ``prompt_eval_count``/``eval_count`` are not exposed by the
    current ``LLMProvider.generate`` contract, so the estimate is used instead.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        num_ctx: int,
        threshold: float = 0.75,
    ) -> None:
        self._llm_provider = llm_provider
        self._num_ctx = num_ctx
        self._threshold = threshold
        self._current_tokens = 0

    @property
    def current_tokens(self) -> int:
        """Approximate tokens accumulated in the current session."""
        return self._current_tokens

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Approximate token count of ``text`` (Russian ≈ 3.5 chars per token)."""
        return max(1, int(len(text) / 3.5))

    def _reset_threshold(self) -> int:
        return int(self._threshold * self._num_ctx)

    @staticmethod
    def _with_anchor(
        system: str | None, anchor: list[str] | None
    ) -> str | None:
        if not anchor:
            return system
        anchor_text = (
            "Уже использованные значения (учитывай для согласованности): "
            + ", ".join(anchor)
        )
        return f"{system}\n\n{anchor_text}" if system else anchor_text

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        anchor: list[str] | None = None,
    ) -> str:
        """Generate a completion, resetting the session when near the limit.

        The reset check runs before sending a message, and only ever after a
        full previous response has been received (never mid-response).
        """
        new_tokens = self._estimate_tokens(prompt)
        if self._current_tokens + new_tokens > self._reset_threshold():
            logger.info(
                "Session reset at %d tokens (threshold=%d)",
                self._current_tokens,
                self._reset_threshold(),
            )
            self._current_tokens = 0
            system = self._with_anchor(system, anchor)

        response = self._llm_provider.generate(prompt, system=system)
        self._current_tokens += new_tokens + self._estimate_tokens(response)
        return response
