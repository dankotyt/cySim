"""Prompts for room generation (contract v1, intent-aware).

The model receives one intent, the rule it must exercise and a small catalog of
artifacts tagged with that intent. Everything else — difficulty-derived points,
the event log, scoring — is the engine's job.
"""
from __future__ import annotations

import json

from ...core.intents import IntentSpec
from .registry import Artifact

ROOM_SYSTEM_PROMPT = """\
/no_think
Ты — методист по информационной безопасности. Ты собираешь учебную «комнату»:
набор объектов, цель сотрудника и краткое задание. Сотрудник исследует объекты
свободно, а опасные действия необратимы.

Жёсткие требования:
1. Отвечай ТОЛЬКО одним валидным JSON-объектом. Без markdown, без пояснений.
2. Используй только объекты из предоставленного каталога, указывая их ref дословно.
3. Комната должна разыгрывать именно то правило, которое передано в запросе.
4. Весь текст — на русском языке. Не придумывай факты и объекты.
5. brief описывает только наблюдаемые факты и заканчивается вопросом. Не называй
   действие, оценку и правильный ответ.
6. Механика комнаты задана полем «цель» объекта; title и brief должны ей
   соответствовать, но не подсказывать её.
"""

_ROOM_SCHEMA = """{
  "v": 1,
  "title": "3-120 символов — короткое название комнаты",
  "brief": "20-400 символов — наблюдаемая ситуация и вопрос «что вы сделаете?»; без действия, оценки и правильного ответа",
  "diff": 2,
  "objs": [
    {"id": "o1", "kind": "<kind из каталога>", "ref": "<ref из каталога>"},
    {"id": "w1", "kind": "<kind из каталога>", "ref": "<ref из каталога>", "via": "o1:link:0"}
  ],
  "goal": "<глагол>(o1)"
}"""


def _few_shot(artifact: Artifact, spec: IntentSpec, benign: bool) -> str:
    """Build a valid example from the actual catalog entry."""
    declared = artifact.goal_actions_for(spec.id)
    verb = declared[0] if declared else (
        spec.benign_verb if benign else spec.threat_verb
    )
    example = {
        "v": 1,
        "title": "Пример комнаты",
        "brief": (
            f"{artifact.summary or artifact.title} Что вы сделаете в этой ситуации?"
        ),
        "diff": 2,
        "objs": [
            {"id": "o1", "kind": artifact.kind, "ref": artifact.ref}
        ],
        "goal": f"{verb}(o1)",
    }
    return json.dumps(example, ensure_ascii=False, indent=2)


def _render_artifact(artifact: Artifact, intent: str) -> str:
    verdict = "легитимный" if artifact.benign else "опасный"
    goals = " | ".join(artifact.goal_actions_for(intent)) or "—"
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
        f"  цель: {goals}\n"
        f"  риски: {risks}\n"
        f"  ссылки: {links}"
    )


def build_room_prompt(
    *,
    context: str,
    spec: IntentSpec,
    department: str,
    catalog: list[Artifact],
    benign: bool,
) -> str:
    """Assemble the per-request room-generation prompt."""
    rendered = "\n".join(
        _render_artifact(artifact, spec.id) for artifact in catalog
    )
    example = _few_shot(catalog[0], spec, benign)
    actions = sorted(
        {
            action
            for artifact in catalog
            if artifact.benign == benign
            for action in artifact.goal_actions_for(spec.id)
        }
    )
    action_hint = ", ".join(actions) or "—"
    if benign:
        variant = (
            "Комната ЛЕГИТИМНАЯ: все объекты в ней безопасны. Цель — действие, "
            f"указанное в поле «цель» легитимного объекта ({action_hint}). "
            "Report легитимного объекта — ошибка (ложное срабатывание)."
        )
    else:
        variant = (
            "Комната ОПАСНАЯ: в ней есть объект с жёсткой ловушкой. Цель — "
            f"действие, указанное в поле «цель» опасного объекта ({action_hint})."
        )
    return f"""\
Собери учебную комнату для отдела «{department}».

## Что разыгрывает комната
Интент: {spec.id} — {spec.title}.
{spec.description}

## Правило компании (контекст)
{context}

## Режим комнаты
{variant}

## Каталог объектов (только из него можно брать ref)
{rendered}

## Требуемый JSON
{_ROOM_SCHEMA}

## Правила сборки
- Объектов 1-5. id объектов короткие и уникальные (o1, w1, u1...).
- ref — дословно из каталога. via указывай только если объект открывается по
  ссылке из другого: "<id-источника>:link:<номер ссылки из каталога>".
- goal — предикат: verb(obj), !, &&, || и скобки. Глаголы: open, inspect, click,
  download, submit, reply, connect, answer, speak, report, dismiss, lock, leave,
  shred, scan, escort, wear, share, return.
- В goal должна быть цель, объявленная в поле «цель» выбранного объекта. Если
  у объекта несколько целей, используй любую из них.
- Не ставь в goal действие, которое для этого объекта является жёсткой ловушкой.
- diff 1-5: 1-2 — явные признаки, 3 — нужно проверить детали,
  4-5 — несколько согласованных признаков.
- brief описывает только наблюдаемую ситуацию и заканчивается вопросом «что вы
  сделаете?». Запрещено называть действие (проверьте, сообщите, откройте,
  сопроводите и т.п.) и давать оценку (опасный, подозрительный, легитимный,
  правильный). Не цитируй политику компании.
- Текст brief должен логически вести к объявленной цели, но не раскрывать её.
- Никаких дополнительных полей (extra, ttl, steps, scoring, risk) — их нет в схеме.

## Пример корректного ответа
{example}"""
