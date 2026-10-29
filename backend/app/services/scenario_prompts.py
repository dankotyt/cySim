"""Prompt templates for LLM scenario generation.

The system prompt carries the role and JSON requirements (plus the Qwen 3
``/no_think`` directive to disable reasoning mode); the per-request prompt
assembled by :func:`build_scenario_prompt` embeds the retrieved rules, the
topic, the target JSON schema and a few-shot example.
"""

SCENARIO_SYSTEM_PROMPT = """\
/no_think
Ты — генератор учебных сценариев по кибербезопасности для сотрудников компании.
На основе извлечённых правил информационной безопасности создай реалистичный сценарий.

Жёсткие требования к ответу:
1. Отвечай ТОЛЬКО одним валидным JSON-объектом. Без markdown, без пояснений, без кода.
2. JSON строго соответствует схеме, приведённой в запросе.
3. Весь текст — на русском языке.
4. Опирайся только на переданные правила компании; не выдумывай факты и правила.
"""

_SCENARIO_JSON_SCHEMA = """{
  "title": "строка — заголовок сценария",
  "step_type": "email_view | phone_call | usb_insert | web_page | search_result",
  "content": "строка — описание ситуации",
  "actions": [
    {
      "id": "a",
      "label": "строка",
      "is_correct": false,
      "consequence": "строка",
      "points": 0
    }
  ],
  "feedback": "строка — пояснение после выбора",
  "scoring": {
    "max_points": 0,
    "passing_score": 0
  }
}"""

_FEW_SHOT_EXAMPLE = """{
  "title": "Подозрительное письмо от «службы поддержки»",
  "step_type": "email_view",
  "content": "На рабочую почту пришло письмо с вложением «Премия_Q3.exe» от «отдела кадров».",
  "actions": [
    {"id": "a", "label": "Открыть вложение", "is_correct": false, "consequence": "Запускается вредоносное ПО, рабочая станция заражена.", "points": 0},
    {"id": "b", "label": "Переслать письмо в службу безопасности", "is_correct": true, "consequence": "Угроза локализована, инцидент зарегистрирован.", "points": 10},
    {"id": "c", "label": "Игнорировать письмо", "is_correct": false, "consequence": "Угроза остаётся невыявленной.", "points": 2}
  ],
  "feedback": "Подозрительные вложения нельзя открывать; о них нужно сообщать в СБ.",
  "scoring": {"max_points": 10, "passing_score": 7}
}"""


def build_scenario_prompt(context: str, topic: str, department: str) -> str:
    """Assemble the per-request generation prompt."""
    return f"""\
Создай учебный сценарий по теме «{topic}» для отдела «{department}».

## Правило компании (контекст)
{context}

## Требуемый JSON-формат
Ответь строго JSON-объектом следующей структуры (поля id, tenant_id, topic,
rule_id, department, created_at добавляются системой — их указывать не нужно):

{_SCENARIO_JSON_SCHEMA}

## Пример корректного ответа
{_FEW_SHOT_EXAMPLE}

## Задание
Сгенерируй сценарий по теме «{topic}» для отдела «{department}» на основе
приведённого правила компании. Используй ТОЛЬКО переданное правило — не выдумывай
факты и не добавляй сведения, которых нет в контексте.
Опиши ровно один шаг сценария (один decision point). Дай ровно 2–4 действия
(actions), ровно одно из которых — правильное (is_correct=true). В scoring задай
max_points как сумму баллов действий, passing_score — порог успешного прохождения
(примерно 60–70% от max_points)."""
