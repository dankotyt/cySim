# 0006. CI на GitHub Actions без CD

- **Статус:** Accepted
- **Дата:** 2026-11-12
- **Связано:** Plan-schedule M0

## Context

- Разработчик один, работа идёт на Windows, репозиторий — GitHub. Деплоя из CI не будет: сервер (или локальная машина заказчика) обновляется вручную через `docker compose`.
- Сейчас в репозитории нет ни CI, ни конфигурации линтеров; тесты запускаются вручную (`backend/pytest.ini`, `asyncio_mode=auto`).
- `requirements.txt` содержит runtime-зависимости и тестовые пакеты; отдельного dev-файла нет.
- Часть проверок требует Docker (`docker compose config`), часть — только Python.
- Секретов в CI быть не должно: сборка корпуса и тесты не обращаются к Hugging Face и vLLM.

## Decision

**Один workflow `.github/workflows/ci.yml` на push в `master`, pull request и ручной запуск. Пять независимых job'ов, без секретов и без деплоя.**

| Job | Что делает | Блокирует merge |
|---|---|---|
| `lint` | `ruff check backend` (синтаксис, неопределённые имена, битые сравнения) | да |
| `test` | `pytest -q` в `backend/` на Python 3.12, SQLite | да |
| `compose` | `docker compose config --quiet` для профилей `gpu`, `low-vram`, `cpu` | да |
| `migrations` | ровно одна head в Alembic (без подключения к БД) | да |
| `docker` | сборка образа `backend` без публикации (после `lint` и `test`) | да |

Правила:

1. `permissions: contents: read`; сторонние action'ы — только официальные (`actions/*`, `docker/*`) с указанием мажорной версии.
2. `concurrency` с `cancel-in-progress: true`, чтобы не жечь минуты на устаревшие коммиты.
3. `pip` кэшируется по `backend/requirements*.txt`; Docker — через `cache-from/to: type=gha`.
4. Для `compose` файл `.env` создаётся из `.env.example` прямо в CI (секретов там нет).
5. Линтер стартует с консервативного набора (`E9,F63,F7,F82`). Расширение до `F401/I/UP/B` — отдельная задача после разовой чистки, чтобы не сделать красный CI нормой.
6. Frontend-job добавится, когда появится `frontend/package.json` (веха M4); в ADR он не проектируется заранее.
7. Сборка корпуса добавляется в CI на вехе M5 (ADR-0005), когда появятся `corpus/brands.yaml` и генератор.
8. CD отсутствует сознательно: нет доверенного окружения, нет секретов деплоя, нет второго человека, который проверит выкатку. Релиз — тег + ручной `docker compose pull/build`.

## Consequences

**Плюсы:** ошибки ловятся до merge; одинаковое окружение у локальной машины и CI; проверка compose ловит расхождения путей после переносов файлов; `migrations` не даёт смёржить ветку с двумя head; сборка образа подтверждает, что Dockerfile не сломан.

**Минусы и риски:** job `docker` медленный (устанавливаются tesseract/poppler) — при частых пушах это минуты; линтер с узким набором пропускает стилевые проблемы; нет тестов фронтенда до M4; зелёный CI не гарантирует, что стенд работает (нет e2e с корпусом).

**Что поддерживать:** версии action'ов; Python 3.12 в CI и локально; при добавлении зависимости — обновлять `requirements.txt`, а не только venv; следить за временем job'ов (цель — до 10 минут суммарно).

## Ручные шаги (владелец репозитория)

1. Включить Actions: **Settings → Actions → General → Allow all actions**.
2. (Рекомендуется) **Settings → Branches → Add branch protection rule** для `master`: require status checks `lint`, `test`, `compose`, `migrations`, `docker`.
3. Секреты **не нужны**. `.env` в CI не требуется и не должен попадать в репозиторий.
4. Локально: `pip install -r backend/requirements-dev.txt` (ruff), затем `ruff check backend` и `pytest` из `backend/`.
