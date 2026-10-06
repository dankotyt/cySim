"""Unit tests for scenario prompt assembly."""
from app.services.scenario_prompts import SCENARIO_SYSTEM_PROMPT, build_scenario_prompt


def test_system_prompt_disables_thinking():
    assert "/no_think" in SCENARIO_SYSTEM_PROMPT


def test_build_scenario_prompt_includes_context_attack_type_and_department():
    prompt = build_scenario_prompt(
        "Правило 1 [phishing]: Сообщать о фишинге", "phishing", "sales"
    )

    assert "Правило 1 [phishing]" in prompt
    assert "phishing" in prompt
    assert "sales" in prompt
    assert '"context"' in prompt
    assert '"steps"' in prompt
    assert '"scoring"' in prompt
