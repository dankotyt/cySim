"""Unit tests for Russian PDF text repair."""
from app.utils.text_repair import repair_russian_text


def test_removes_soft_hyphen_and_zero_width_chars():
    assert repair_russian_text("пароль\u00ad\u200b\u200c") == "пароль"


def test_replaces_non_breaking_space():
    assert repair_russian_text("пароль\u00a0и\u00a0логин") == "пароль и логин"


def test_expands_ligatures():
    assert repair_russian_text("\ufb01le \ufb02ow") == "file flow"


def test_repairs_latin1_mojibake():
    original = "информация"
    mojibake = original.encode("utf-8").decode("latin-1")
    assert repair_russian_text(mojibake) == original


def test_ascii_is_unchanged():
    text = "First line\nSecond line"
    assert repair_russian_text(text) == text


def test_preserves_plain_cyrillic():
    text = "Правила информационной безопасности"
    assert repair_russian_text(text) == text
