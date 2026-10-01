"""Attack-type → RAG query mapping shared by the document and scenario services.

Keys are the canonical attack types: they must stay in sync with the
``AttackType`` literal in :mod:`app.models.scenario`.
"""

ATTACK_QUERIES: dict[str, str] = {
    "phishing": "фишинг подозрительные письма вложения ссылки пароли учётные данные",
    "vishing": "телефонный звонок служба безопасности код из sms подтверждение кода",
    "baiting": "флешка usb найденный носитель бонус бесплатно скачать файл",
    "pretexting": "отдел кадров новый сотрудник увольнение приказ перевод",
    "tailgating": "пропуск дверь посторонний незнакомый физический доступ",
    "quid_pro_quo": "техподдержка помощь взамен обновление настроить починить",
    "social_media_osint": "соцсети профиль должность публикация конференция linkedin",
    "usb_drop": "usb-носитель подброшенная флешка парковка неизвестный носитель",
}
