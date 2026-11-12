# CI: что запускается и что делать руками

Решение и обоснование — `docs/adr/0006-ci-baseline.md`. Здесь — эксплуатация.

## Что проверяется

| Job | Команда | Зачем |
|---|---|---|
| `lint` | `ruff check backend` | синтаксис, неопределённые имена, битые сравнения |
| `test` | `pytest -q` (в `backend/`) | регрессии сервисов и репозиториев |
| `compose` | `docker compose config --quiet` для `gpu`, `low-vram`, `cpu` | битые пути и профили после переносов файлов |
| `migrations` | `alembic heads` ровно одна | ветвление истории миграций |
| `docker` | сборка `backend/Dockerfile` без push | Dockerfile и зависимости |

Триггеры: push в `master`, любой pull request, ручной запуск (`workflow_dispatch`).

## Что нужно сделать в GitHub (один раз)

1. **Settings → Actions → General → Allow all actions and reusable workflows.**
2. **Settings → Branches → Add branch protection rule** для `master`:
   - Require a pull request before merging (по желанию, если работаешь через PR);
   - Require status checks: `lint`, `test`, `compose`, `migrations`, `docker`.
3. **Секреты не нужны.** CI не обращается к Hugging Face, vLLM и внешним API. `.env` в репозиторий не добавляется: для `compose`-job он создаётся из `.env.example` внутри раннера.
4. Если репозиторий форкнут — Actions включаются в форке отдельно.

## Локальный прогон (Windows)

```bat
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.venv\Scripts\python.exe -m ruff check backend
cd backend && ..\.venv\Scripts\python.exe -m pytest -q
```

```bat
copy .env.example .env
docker compose -f docker-compose.yaml --profile gpu config --quiet
docker compose -f docker-compose.yaml --profile low-vram config --quiet
docker compose -f docker-compose.yaml --profile cpu config --quiet
```

Проверка миграций без БД:

```bat
cd backend && ..\.venv\Scripts\python.exe -c "from alembic.config import Config; from alembic.script import ScriptDirectory; h=ScriptDirectory.from_config(Config('alembic.ini')).get_heads(); assert len(h)==1, h; print(h[0])"
```

## Если CI упал

| Симптом | Причина | Что делать |
|---|---|---|
| `ruff: F821 undefined name` | опечатка или забытый импорт | исправить имя/импорт |
| `ruff: E999` | синтаксическая ошибка | запустить `python -m compileall backend` локально |
| `pytest` падает только в CI | тест зависит от локального `.env` или данных | тест должен создавать `Settings()` без `.env`; Проверить, что не читается файл из `data/` |
| `compose config` падает | нет `.env` или битый YAML | `copy .env.example .env`, затем повторить; проверить отступы |
| `alembic` две head | параллельные миграции | `alembic merge -m "merge heads" <a> <b>` |
| `docker` job > 10 минут | нет кэша слоёв | первый прогон холодный, дальше `type=gha`; проверить, что не меняется `requirements.txt` без причины |

## Следующий шаг (не входит в M0)

1. Разовая чистка и расширение правил ruff до `["E4", "E7", "E9", "F", "I", "UP", "B"]`, затем `ruff check backend --fix` и отдельный коммит.
2. Job `frontend` (npm ci, tsc, vitest) — на вехе M4, когда появится `frontend/package.json`.
3. Job `corpus` (сборка `corpus/dist` + тесты консистентности) — на вехе M5.
4. E2E smoke (Playwright) против `docker compose` — после сценария «правило → сценарий → шаг → ответ → балл».

## Почему нет CD

Нет доверенного окружения, секретов деплоя и второго человека для проверки выкатки. Релиз — вручную: тег, `docker compose --profile <gpu|low-vram|cpu> up --build -d`, проверка `/health`. Автоматизация деплоя появится только при появлении постоянного стенда (отдельный ADR).
