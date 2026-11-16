"""Prompts for room generation (contract v1).

The model is asked for a small JSON object referencing artifacts it was shown.
Everything else — difficulty-derived points, the event log, scoring — is the
engine's job, so the prompt stays short.
"""
from __future__ import annotations

from .registry import Artifact

ROOM_SYSTEM_PROMPT = """\
/no_think
Ты — методист по информационной безопасности. Ты собираешь учебную «комнату»:
набор объектов, цель сотрудника и краткое задание. Сотрудник исследует объекты
свободно, а опасные действия необратимы.

Жёсткие требования:
1. Отвечай ТОЛЬКО одним валидным JSON-объектом. Без markdown, без пояснений.
2. Используй только объекты из предоставленного каталога, указывая их ref дословно.
3. Весь текст — на русском языке.
4. Не придумывай факты, правила и объекты, которых нет в запросе.
"""

_ROOM_SCHEMA = """{
  "v": 1,
  "title": "3-120 символов — короткое название комнаты",
  "brief": "20-400 символов — что за ситуация и что требуется от сотрудника; без подсказки правильного ответа",
  "diff": 2,
  "objs": [
    {"id": "o1", "kind": "email", "ref": "fx:email:em-0002"},
    {"id": "w1", "kind": "site", "ref": "fx:site:s-0001", "via": "o1:link:0"}
  ],
  "goal": "report(o1)"
}"""

_FEW_SHOT = """{
  "v": 1,
  "title": "Сверка за квартал",
  "brief": "На рабочую почту пришло письмо с вложением от неизвестного отправителя. Решите, что делать с письмом и вложением, действуя по политике компании.",
  "diff": 2,
  "objs": [{"id": "o1", "kind": "email", "ref": "fx:email:em-0001"}],
  "goal": "report(o1)"
}"""


def _render_artifact(artifact: Artifact) -> str:
    verdict = "легитимный" if artifact.benign else "опасный"
    risks = (
        "; ".join(
            f"{risk.on}={risk.level} (штраф {risk.pen}, урок {risk.lesson})"
            for risk in artifact.risk
        )
        or "нет"
    )
    links = (
        "; ".join(
            f"{index}:{target}" for index, target in enumerate(artifact.links)
        )
        or "нет"
    )
    return (
        f"- ref={artifact.ref} | kind={artifact.kind} | {verdict} | "
        f"«{artifact.title}»\n"
        f"  описание: {artifact.summary or '—'}\n"
        f"  риски: {risks}\n"
        f"  ссылки: {links}"
    )


def build_room_prompt(
    *,
    context: str,
    topic: str,
    department: str,
    catalog: list[Artifact],
) -> str:
    """Assemble the per-request room-generation prompt."""
    rendered = "\n".join(_render_artifact(artifact) for artifact in catalog)
    return f"""\
Собери учебную комнату по теме «{topic}» для отдела «{department}».

## Правило компании (контекст)
{context}

## Каталог объектов (только из него можно брать ref)
{rendered}

## Требуемый JSON
{_ROOM_SCHEMA}

## Правила сборки
- Объектов 1-5. id объектов короткие и уникальные (o1, w1, u1...).
- ref — дословно из каталога. Поле via указывай только если объект открывается
  по ссылке из другого объекта: "<id-источника>:link:<номер ссылки из каталога>".
- goal — предикат: verb(obj), !, &&, || и скобки. Глаголы: open, inspect, click,
  download, submit, reply, connect, answer, speak, report, dismiss.
- Цель комнаты: report для опасного объекта и dismiss для легитимного.
  В goal обязателен хотя бы один report опасного объекта.
- Не ставь в goal действие, которое для этого объекта является жёсткой ловушкой.
- diff 1-5: 1-2 — явные признаки, 3 — нужно проверить домен/вложение,
  4-5 — несколько согласованных признаков.
- brief описывает ситуацию и задачу, но не называет правильный ответ.
- Никаких дополнительных полей (extra, ttl, steps, scoring, risk) — их нет в схеме.

## Пример корректного ответа
{_FEW_SHOT}"""
