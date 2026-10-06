"""Robust parsing of LLM responses that may be wrapped in markdown fences.

LLMs frequently return a fenced code block or add prose around the payload.
These helpers strip fences, fall back to the first ``{...}`` / ``[...]`` block,
and validate the top-level type.
"""
import json


def _strip_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    return text


def _extract_bracket(text: str, open_char: str, close_char: str) -> str:
    start = text.find(open_char)
    end = text.rfind(close_char)
    if start == -1 or end <= start:
        raise ValueError(
            f"LLM output contains no {open_char}{close_char} block"
        )
    return text[start : end + 1]


def parse_llm_json_object(raw: str) -> dict:
    """Parse an LLM response into a JSON object (dict)."""
    text = _strip_fences(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_bracket(text, "{", "}"))
    if not isinstance(parsed, dict):
        raise ValueError("LLM output must be a JSON object")
    return parsed


def parse_llm_json_array(raw: str) -> list:
    """Parse an LLM response into a JSON array (list)."""
    text = _strip_fences(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = json.loads(_extract_bracket(text, "[", "]"))
    if not isinstance(parsed, list):
        raise ValueError("LLM output must be a JSON array")
    return parsed
