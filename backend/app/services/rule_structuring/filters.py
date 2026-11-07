"""Post-processing filters — mirror scripts/filters.py + scripts/inference.py."""

import re
from difflib import SequenceMatcher

_REFERENCE_MARKERS = (
    "федеральный закон", "федеральным законом", "фз «", "фз №", "фз-",
    "постановление правительства", "постановлением правительства",
    "приказ фстэк", "приказом фстэк", "приказ фсб", "приказом фсб",
    "приказ росстандарта", "методическим документом",
    "национальными стандартами", "национальный стандарт",
    "гост р ", "гост ", "iso ", "iso/iec", "nist",
)

_ACTION_MARKERS = (
    "должен", "должна", "должны", "обязан", "обязана", "обязаны",
    "запрещ", "не допуска", "нельзя", "не разреша",
    "следует", "необходимо", "надлежит", "требуется",
    "не реже", "не позднее", "в течение", "немедленно",
    "только при", "только с", "только после", "только по",
    "сообща", "уведом", "обеспечива", "устанавлива", "проверя",
    "регистриру", "блокиру", "отключа", "передава", "храни",
    "использу", "выполня", "осуществля", "проводит",
    "ведёт", "ведет", "соблюда", "применя", "ознакомля",
    "подписыва", "согласовыва", "назнача", "утвержда",
    "настраива", "определя", "документиру", "оформля", "фиксиру",
    "направля", "предоставля", "запрашива",
    "удаля", "обновля", "резервиру", "восстанавлива",
    "информиру", "консультиру", "обуча", "разъясня",
    "контролиру", "отслежива", "анализиру", "оценива",
    "планиру", "иницииру", "реализу", "внедря", "разрабатыва",
    "сопровожда", "эксплуатиру", "размеща", "разреша",
)

_DEFINITION_RE = re.compile(
    r"(термины и определения|"
    r"применяются в значени|"
    r"определяются в соответствии|"
    r"используются в значениях|"
    r"в целях обеспечения единообразного понимания)",
    re.IGNORECASE,
)

_META_RE = re.compile(
    r"^(настоящий регламент|"
    r"регламент\s+(устанавливает|определяет|распространяется|разработан|подготовлен)|"
    r"документ\s+(устанавливает|определяет)|"
    r"стандарт\s+(устанавливает|определяет))",
    re.IGNORECASE,
)

_DEFINITION_LINE_RE = re.compile(
    r"^(?:[А-ЯЁA-Z][\w\-]+(?:\s+[а-яёa-z][\w\-]*){0,2}"
    r"|[А-ЯЁA-Z]{2,}(?:\s*\([^)]+\))?)"
    r"\s*[–—]\s*"
    r"(?!должен|обязан|запрещ|настраива|определя|ведёт|ведет|"
    r"обеспечива|проводит|применя|соблюда|использу|"
    r"выполня|осуществля|устанавлива|утвержда|назнача)"
    r".{15,}$",
)

_ABBREV_RE = re.compile(
    r"^[А-ЯЁA-Z]{2,}\s*[–—]\s*[А-ЯЁA-Z][^\n]*\.?$"
)


def _has_reference(line: str) -> bool:
    t = line.lower()
    return any(m in t for m in _REFERENCE_MARKERS)


def _has_action(line: str) -> bool:
    t = line.lower()
    return any(m in t for m in _ACTION_MARKERS)


def _count_references(line: str) -> int:
    t = line.lower()
    return len(re.findall(r"\b(гост|фз|iso|nist)\b", t))


def _is_junk_rule(text: str) -> bool:
    """Line is a reference / definition / meta, not an actionable rule."""
    t = text.strip()
    if not t:
        return True
    if len(t) < 20:
        return True

    tl = t.lower().rstrip(" .,;:")

    if re.match(
        r"^(федеральный закон|федеральным законом|"
        r"постановлени|приказ(ом)?\s|приказ[аеу]?\s|"
        r"гост|iso|nist|"
        r"методическим документом|"
        r"национальными стандартами|"
        r"иными нормативными|"
        r"политикой|политика|"
        r"стандартом|стандарт\s)",
        tl,
    ):
        if not _has_action(t):
            return True

    if _count_references(t) >= 2:
        return True
    if _count_references(t) == 1 and not _has_action(t):
        return True
    if _has_reference(t) and not _has_action(t):
        return True

    if _DEFINITION_LINE_RE.match(t) and not _has_action(t):
        return True
    if _ABBREV_RE.match(t):
        return True
    if _DEFINITION_RE.search(t):
        return True
    if _META_RE.search(t):
        return True

    return False


_PERSON_SUBJECTS = (
    "сотрудник", "работник", "пользователь", "администратор", "специалист",
    "оператор", "руководитель", "директор", "начальник", "инженер",
    "программист", "разработчик", "аналитик", "бухгалтер",
    "секретарь", "охранник", "стажёр", "стажер",
    "подрядчик", "контрагент", "обучающийся", "ученик", "студент",
    "заявитель", "посетитель", "персонал",
)

_STRONG_MODAL = (
    "должен", "должна", "должно", "должны",
    "обязан", "обязана", "обязаны",
    "запрещено", "запрещается", "запрещены",
    "нельзя", "необходимо", "следует", "требуется",
    "разрешено", "разрешается", "допускается",
)


def _is_employee_rule(text: str) -> bool:
    t = text.lower()
    if any(p in t for p in _PERSON_SUBJECTS):
        return True
    if any(m in t for m in _STRONG_MODAL):
        return True
    return False


def _normalize(text: str) -> str:
    return " ".join(text.split())

def _normalize_for_match(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def _fuzzy_in_chunk(text: str, chunk_norm: str, prefix_len: int = 40, threshold: float = 0.78) -> bool:
    t = _normalize_for_match(text)
    if not t:
        return False
    if t in chunk_norm:
        return True
    if len(t) >= prefix_len and t[:prefix_len] in chunk_norm:
        return True

    if ":" in text:
        header_raw, bullet_raw = text.split(":", 1)
        header = _normalize_for_match(header_raw)
        bullet = _normalize_for_match(bullet_raw)
        if (len(header) >= 3 and len(bullet) >= 10
                and header in chunk_norm and bullet in chunk_norm):
            return True

    max_prefix = min(60, len(t) - 15)
    for plen in range(max_prefix, 14, -1):
        prefix = t[:plen]
        if prefix not in chunk_norm:
            continue
        remainder = t[plen:].strip()
        if len(remainder) >= 15 and remainder in chunk_norm:
            return True

    w = len(t)
    if w > len(chunk_norm):
        return False
    step = max(1, w // 4)
    for i in range(0, len(chunk_norm) - w + 1, step):
        window = chunk_norm[i:i + w]
        if SequenceMatcher(None, t, window).ratio() >= threshold:
            return True
    return False
