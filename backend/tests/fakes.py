"""Shared test doubles and fixture payloads."""
import json

from app.services.llm_provider import LLMProvider

# A room that passes L0-L3 for the attachment intent used across tests: one
# malicious email with a hard attachment trap and a soft reply trap.
VALID_ROOM = {
    "v": 1,
    "title": "Сверка за квартал",
    "brief": (
        "На рабочую почту пришло письмо с вложением от неизвестного отправителя. "
        "Что вы сделаете в этой ситуации?"
    ),
    "diff": 2,
    "intent": "attachment_macro",
    "objs": [{"id": "o1", "kind": "email", "ref": "fx:email:em-0001"}],
    "goal": "report(o1)",
}

VALID_ROOM_JSON = json.dumps(VALID_ROOM, ensure_ascii=False)


def room_json(**overrides: object) -> str:
    """Return a valid room payload with selected fields overridden."""
    payload = {**VALID_ROOM, **overrides}
    return json.dumps(payload, ensure_ascii=False)


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
        return VALID_ROOM_JSON

    async def is_available(self) -> bool:
        return True
