"""Tests for the LLM session manager."""
from app.services.session_manager import SessionManager
from tests.fakes import FakeLLMProvider


class _EmptyLLM(FakeLLMProvider):
    def generate(self, prompt, **kwargs):
        self.calls.append(prompt)
        return ""


def test_estimate_tokens():
    assert SessionManager._estimate_tokens("") == 1
    assert SessionManager._estimate_tokens("1234567") == 2  # 7 / 3.5


def test_with_anchor():
    result = SessionManager._with_anchor("SYS", ["phishing", "passwords"])
    assert result.startswith("SYS\n\nУже использованные значения")
    assert "phishing" in result
    assert SessionManager._with_anchor("SYS", None) == "SYS"
    assert SessionManager._with_anchor("SYS", []) == "SYS"
    assert SessionManager._with_anchor(None, None) is None


def test_generate_returns_response_and_tracks_tokens():
    llm = FakeLLMProvider()
    sm = SessionManager(llm, num_ctx=10000, threshold=0.75)

    response = sm.generate("hello")

    assert response
    assert sm.current_tokens > 0


def test_generate_resets_when_over_threshold():
    llm = _EmptyLLM()
    sm = SessionManager(llm, num_ctx=1000, threshold=0.75)  # threshold 750 tokens

    for _ in range(7):
        sm.generate("a" * 350)  # ~100 tokens + 1 (empty response) each

    before = sm.current_tokens
    sm.generate("a" * 350)  # crosses the threshold -> reset

    assert sm.current_tokens < before
