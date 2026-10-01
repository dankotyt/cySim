"""Prompt templates for LLM scenario generation.

The system prompt carries the role and JSON requirements (plus the Qwen 3
``/no_think`` directive to disable reasoning mode); the per-request prompt
assembled by :func:`build_scenario_prompt` embeds the retrieved rules, the
attack type, the target JSON schema and a few-shot example.
"""

SCENARIO_SYSTEM_PROMPT = """\
/no_think
Ты — генератор учебных сценариев по кибербезопасности для сотрудников компании.
На основе извлечённых правил информационной безопасности создай реалистичный сценарий атаки.

Жёсткие требования к ответу:
1. Отвечай ТОЛЬКО одним валидным JSON-объектом. Без markdown, без пояснений, без кода.
2. JSON строго соответствует схеме, приведённой в запросе.
3. Весь текст — на русском языке.
4. Опирайся только на переданные правила компании; не выдумывай факты и правила.
"""

_SCENARIO_JSON_SCHEMA = """{
  "title": "строка — заголовок сценария",
  "context": {
    "company_rule": "строка — ссылка на правило (например: Правило 1 [phishing]: ...)",
    "source": "строка — документ-источник правила",
    "page": 0
  },
  "steps": [
    {
      "step_id": "1",
      "type": "email_view | phone_call | usb_insert | web_page | search_result",
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
      "correct_action": "строка — id правильного действия"
    }
  ],
  "scoring": {
    "max_points": 0,
    "passing_score": 0
  }
}"""

_FEW_SHOT_EXAMPLE = """{
  "title": "Подозрительное письмо от «службы поддержки»",
  "context": {
    "company_rule": "Правило 1 [phishing]: Сообщать о подозрительных письмах в службу безопасности",
    "source": "policy.txt",
    "page": 2
  },
  "steps": [
    {
      "step_id": "1",
      "type": "email_view",
      "content": "На рабочую почту пришло письмо с вложением «Премия_Q3.exe» от «отдела кадров».",
      "actions": [
        {"id": "a", "label": "Открыть вложение", "is_correct": false, "consequence": "Запускается вредоносное ПО, рабочая станция заражена.", "points": 0},
        {"id": "b", "label": "Переслать письмо в службу безопасности", "is_correct": true, "consequence": "Угроза локализована, инцидент зарегистрирован.", "points": 10},
        {"id": "c", "label": "Игнорировать письмо", "is_correct": false, "consequence": "Угроза остаётся невыявленной.", "points": 2}
      ],
      "feedback": "Подозрительные вложения нельзя открывать; о них нужно сообщать в СБ.",
      "correct_action": "b"
    },
    {
      "step_id": "2",
      "type": "web_page",
      "content": "Сотрудник перешёл по ссылке из письма и попал на страницу, запрашивающую логин и пароль.",
      "actions": [
        {"id": "a", "label": "Ввести логин и пароль", "is_correct": false, "consequence": "Учётные данные похищены.", "points": 0},
        {"id": "b", "label": "Закрыть страницу и сообщить в СБ", "is_correct": true, "consequence": "Фишинг-сайт задокументирован и заблокирован.", "points": 10}
      ],
      "feedback": "Никогда не вводите учётные данные на страницах, на которые перешли из подозрительных писем.",
      "correct_action": "b"
    }
  ],
  "scoring": {"max_points": 20, "passing_score": 14}
}"""


def build_scenario_prompt(context: str, attack_type: str) -> str:
    """Assemble the per-request generation prompt."""
    return f"""\
Создай учебный сценарий атаки типа «{attack_type}».

## Правила компании (контекст)
{context}

## Требуемый JSON-формат
Ответь строго JSON-объектом следующей структуры (поля id, tenant_id, attack_type,
created_at добавляются системой — их указывать не нужно):

{_SCENARIO_JSON_SCHEMA}

## Пример корректного ответа
{_FEW_SHOT_EXAMPLE}

## Задание
Сгенерируй сценарий атаки типа «{attack_type}» на основе приведённых правил компании.
steps — от 3 до 5 шагов. В scoring задай max_points как сумму баллов всех шагов,
passing_score — порог, который сотрудник должен набрать для успешного прохождения
(примерно 60–70% от max_points). Дай ровно 2–4 действия (actions) на каждый шаг,
ровно одно из которых — правильное (is_correct=true)."""
