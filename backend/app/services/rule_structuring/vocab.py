"""Controlled vocabularies for LoRA rule extraction — mirror scripts/prompts.py.

Ported verbatim from the training side; any drift between training and
inference degrades quality.
"""

import re

from ...core.topics import ALLOWED_TOPICS

_AUDIENCES = """\
general - общая аудитория: правило касается всех сотрудников компании без исключения
management - руководство (директора, топ-менеджмент, руководители подразделений, заведующие)
it - IT-специалисты (сисадмины, DevOps, техподдержка)
security - служба ИБ и ответственные за безопасность (администратор безопасности)
developers - разработчики (программисты, QA, архитекторы)
privileged - привилегированные пользователи (админы домена, root, DBA)
finance - финансы и бухгалтерия
hr - отдел кадров
legal - юридический отдел
physical_security - физическая охрана
remote - удалённые сотрудники
contractors - подрядчики и внешние специалисты
third_parties - третьи стороны (партнёры, поставщики)
office_workers - офисные сотрудники
interns - стажёры и практиканты
other - роль не определена или правило не про сотрудника (описание системы/процесса)"""

VALID_AUDIENCES: frozenset[str] = frozenset({
    "general", "management", "it", "security", "developers", "privileged",
    "finance", "hr", "legal", "physical_security", "remote", "contractors",
    "third_parties", "office_workers", "interns", "other",
})

# Validation uses the project's vocabulary (source of truth for SecurityRule).
VALID_TOPICS: frozenset[str] = frozenset(ALLOWED_TOPICS)

_RULE_RE = re.compile(
    r"^audience=([a-z_]+(?:\s*,\s*[a-z_]+)*)"
    r"\s*\|\s*topic=([a-z_]+)\s*\|\s*(.+)$"
)


def _validate_audience(value: str) -> bool:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return bool(parts) and all(p in VALID_AUDIENCES for p in parts)
