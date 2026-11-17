"""Fixed vocabulary of scenario intents.

An intent is *what situation the room trains* — narrower than the rule topic
and independent of the delivery channel. The room generator may only pick
artifacts tagged with the resolved intent, which is what keeps a screen-lock
rule from producing a phishing email.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentSpec:
    """Description of one intent and the safe actions that end it."""

    id: str
    title: str
    description: str
    kinds: tuple[str, ...]
    threat_verb: str
    benign_verb: str


INTENTS: dict[str, IntentSpec] = {
    spec.id: spec
    for spec in (
        IntentSpec(
            "phishing_email",
            "Подозрительное письмо",
            "Письмо с просьбой перейти по ссылке, открыть вложение или ответить.",
            ("email", "site"),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "attachment_macro",
            "Вложение с макросом",
            "Документ или архив во вложении, запуск которого вредит.",
            ("email", "pdf"),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "credential_form",
            "Форма входа или код",
            "Копия страницы входа, форма ввода пароля или кода подтверждения.",
            ("site", "email"),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "usb_found",
            "Найденный носитель",
            "Флешка неизвестного происхождения и попытка её подключить.",
            ("usb",),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "phone_code",
            "Звонок с запросом секрета",
            "Звонящий просит код, пароль или данные под благовидным предлогом.",
            ("call",),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "remote_tool",
            "Удалённый доступ и настройки",
            "Просьба установить программу, сертификат или отключить защиту.",
            ("call", "site"),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "invoice_change",
            "Смена реквизитов",
            "Письмо, счёт или форма с изменёнными банковскими реквизитами.",
            ("email", "site", "pdf", "call"),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "data_disclosure",
            "Передача данных вне контура",
            "Отправка документов на личную почту, копии «для удобства», фото экрана.",
            ("email", "site", "desk"),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "password_sharing",
            "Передача пароля или учётной записи",
            "Коллега, подрядчик или «поддержка» просит пароль, доступ или сессию.",
            ("email", "call"),
            "report",
            "dismiss",
        ),
        IntentSpec(
            "unattended_session",
            "Экран без присмотра",
            "Рабочая станция остаётся разблокированной при отходе сотрудника.",
            ("workstation",),
            "lock",
            "leave",
        ),
        IntentSpec(
            "shoulder_surfing",
            "Данные в зоне обзора",
            "Экран или документы видны посетителю, стоящему рядом.",
            ("workstation", "desk"),
            "lock",
            "leave",
        ),
        IntentSpec(
            "clean_desk",
            "Документы на столе",
            "Документы заявителей оставлены открытыми, без присмотра или не уничтожены.",
            ("desk",),
            "lock",
            "leave",
        ),
        IntentSpec(
            "tailgating",
            "Проход без пропуска",
            "Посторонний пытается пройти в служебную зону вместе с сотрудником.",
            ("door",),
            "escort",
            "scan",
        ),
        IntentSpec(
            "visitor_handling",
            "Сопровождение посетителя",
            "Посетитель, курьер или подрядчик в служебной зоне без сопровождения.",
            ("door", "badge"),
            "escort",
            "scan",
        ),
        IntentSpec(
            "badge_sharing",
            "Пропуск или ключ",
            "Пропуск носят не на виду, передают другому или не возвращают.",
            ("badge",),
            "report",
            "wear",
        ),
    )
}

INTENT_IDS: tuple[str, ...] = tuple(INTENTS)
NOT_REPRESENTABLE = "not_representable"


def get_intent(intent_id: str) -> IntentSpec | None:
    """Return the spec for ``intent_id`` or ``None``."""
    return INTENTS.get(intent_id)


def intent_catalog_text() -> str:
    """Render the intent list for the classification prompt."""
    return "\n".join(
        f"- {spec.id}: {spec.title} — {spec.description}"
        for spec in INTENTS.values()
    )
