"""Shared test doubles."""
from app.services.llm_provider import LLMProvider


VALID_SCENARIO_JSON = (
    '{"title": "Фишинг-тест", '
    '"step_type": "email_view", '
    '"content": "Письмо с вложением", '
    '"actions": ['
    '{"id": "a", "label": "Открыть", "is_correct": false, "consequence": "Заражение", "points": 0}, '
    '{"id": "b", "label": "Сообщить в СБ", "is_correct": true, "consequence": "Локализовано", "points": 10}'
    '], '
    '"feedback": "Правильно", '
    '"scoring": {"max_points": 10, "passing_score": 7}}'
)


class FakeLLMProvider(LLMProvider):
    """Deterministic LLM provider that returns canned responses in order."""

    name = "fake"

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses) if responses else []
        self.calls: list[str] = []

    async def generate(self, prompt: str, **kwargs) -> str:
        self.calls.append(prompt)
        if self._responses:
            return self._responses.pop(0)
        return VALID_SCENARIO_JSON

    async def is_available(self) -> bool:
        return True
