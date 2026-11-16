# Архитектура CyberSim

Документ фиксирует **текущее состояние** (as-is) и целевые решения, принятые в ADR. Если код и ADR расходятся — это технический долг, он перечислен в §11.

Дата обновления: 2026-11-16.

## 1. Что реализовано сейчас

| Реализовано | Не реализовано (план) |
|---|---|
| FastAPI backend: загрузка документов → извлечение правил → генерация комнат (ADR-0008) | SPA-кабинет сотрудника/админа (ADR-0003) |
| PostgreSQL: `documents`, `security_rules`, `departments`, `scenarios`, `scenario_attempts` | Песочница и персональное состояние (ADR-0002) |
| LLM только по HTTP: vLLM (LoRA `secpol`) или Ollama/OpenAI | Веб-корпус, `site-service`, браузер (ADR-0005) |
| Событийный движок комнат, `attempts` API, скоринг `max − Σpen − blind` | UI-движок комнат, виртуальный день и таймаут попытки |
| CI на GitHub Actions (5 job'ов) | Аутентификация, роли, tenant/employee из сессии (ADR-0004) |
| Локальный тест-UI `upload.html` | |

Backend — модульный монолит: API → сервисы → репозитории → ORM. Отдельного фронтенда и отдельных сервисов пока нет.

## 2. Компоненты

```
клиент (upload.html / будущая SPA)
        │ HTTP
        ▼
┌──────────────────────────┐        ┌───────────────────────────┐
│ backend (FastAPI :8000)  │───────▶│ PostgreSQL 16 (:5432)     │
│ API → services → repos   │        │ 5 таблиц, Alembic         │
└───────────┬──────────────┘        └───────────────────────────┘
            │ OpenAI-compatible HTTP
            ▼
┌──────────────────────────┐   profile gpu / low-vram
│ vLLM (:8001, host 18001) │   модель Qwen2.5-7B-Instruct + LoRA "secpol"
└──────────────────────────┘
            или profile cpu
┌──────────────────────────┐
│ Ollama (:11434)          │   qwen2.5:7b-instruct
└──────────────────────────┘
```

План (ADR-0003, ADR-0005): появляются `frontend/` (React/Vite) и `site-service` (статика корпуса + `/go`, `/sim/forms`, `/trust`) на отдельном origin.

## 3. Модули `backend/app`

| Модуль | Ответственность |
|---|---|
| `api/v1/documents.py` | `POST /upload`, `GET /{id}`, `DELETE /{id}` |
| `api/v1/rules.py` | `GET` (список по тенанту), `GET /{id}`, `DELETE /{id}` |
| `api/v1/scenarios.py` | `POST /generate`, `POST /generate-all`, `GET` (публичный список), `GET /{id}` (публичный), `POST /{id}/attempts`, `DELETE /{id}` |
| `api/v1/attempts.py` | `GET` (список), `GET /{id}`, `POST /{id}/events` |
| `core/config.py` | `Settings` (pydantic-settings), `.env` в корне репозитория, `DEFAULT_TENANT_ID`, `DEFAULT_EMPLOYEE_ID` |
| `core/topics.py` | Единый словарь `ALLOWED_TOPICS` (18 тем) |
| `core/database.py` | Async engine и фабрика сессий (asyncpg) |
| `core/logging.py` | Централизованная настройка логов |
| `core/rule_text.py` | Нормализация текста правила и `content_hash` |
| `models/document.py` | `Document`, `UploadResponse`, `Chunk`, `SecurityRule`, `DeleteResponse` |
| `models/scenario.py` | `Room`, `RoomObject`, `Scenario`, `PublicScenario`, `RuleSnapshot`, `Attempt`, `AttemptState`, запросы/ответы |
| `models/department.py` | `Department.allowed_topics` |
| `models/db_models.py` | ORM: `documents`, `security_rules`, `departments`, `scenarios`, `scenario_attempts` |
| `repositories/document_repository.py` | CRUD метаданных документа |
| `repositories/security_rule_repository.py` | Создание пачкой, выборки по тенанту/темам/фильтрам, удаление |
| `repositories/department_repository.py` | CRUD отделов, `get_or_create_default` |
| `repositories/scenario_repository.py` | CRUD комнат, fingerprint, выборка по правилу |
| `repositories/scenario_attempt_repository.py` | Журнал попыток: создание, обновление, выборки |
| `services/document_service.py` | Пайплайн загрузки: validate → parse → chunk → structure → rules → metadata |
| `services/document_validator.py` | MIME (libmagic), расширение, объём, минимум текста/чанков |
| `services/rule_structuring/` | LoRA-структурирование: `vocab`, `prompts`, `filters`, `structurer` |
| `services/scenario_context.py` | `SecurityRule` → текстовый блок промпта |
| `services/scenario_generation/` | `goals` (грамматика цели), `registry` (fixture-артефакты и уроки), `planner`, `prompts`, `pipeline`, `validators` (L0–L3), `scoring` (движок событий), `dedup` |
| `services/scenario_service.py` | Генерация комнат, CRUD, попытки, публичные DTO |
| `services/llm_provider.py` | `LLMProvider`, `OpenAICompatibleProvider`, `VLLMProvider`, фабрика |
| `services/session_manager.py` | Бюджет контекста LLM-сессии (anchor + сброс) |
| `utils/parsers.py` | PDF/DOCX/TXT + OCR + mojibake fix |
| `utils/chunking.py` | `RecursiveCharacterTextSplitter` (в памяти) |
| `utils/llm_json.py` | Извлечение JSON из ответа LLM |
| `utils/ocr.py` | pytesseract fallback |
| `utils/text_repair.py` | Восстановление cp1251-mojibake |
| `main.py` | `create_app`, CORS, lifespan, exception handlers, `/health` |

## 4. Потоки

### 4.1 Документ → правила

1. `POST /api/v1/documents/upload` (multipart; `tenant_id` — поле формы, см. §10).
2. Проверка расширения и размера; `sha256` содержимого; создаётся запись `documents` со `status=processing`.
3. `parse_file` и `chunk_document` выполняются в `asyncio.to_thread`; текст и чанки **в памяти**.
4. `DocumentValidator`: MIME, объём, `min_document_chars`, `min_document_chunks`.
5. `LoRARuleStructurer.structure(chunks, tenant_id, document_id)` — почанковый вызов LLM; ответ формата `audience=<код> | topic=<код> | <правило>` парсится и валидируется по `ALLOWED_TOPICS` / `VALID_AUDIENCES`.
6. `security_rules.create_many` → правила с `document_id`; дубликаты по `(topic, нормализованный текст)` в рамках тенанта пропускаются.
7. `documents.status=processed`, `rule_count` = число реально вставленных правил; при исключении — `status=failed`, ошибка пробрасывается как `ProcessingError`.

Содержимое и чанки в БД **не сохраняются**.

### 4.2 Генерация комнаты (ADR-0008)

1. `POST /generate` (одно правило) или `/generate-all` (пачка).
2. Отдел → `allowed_topics`; правила фильтруются по `tenant_id`, затем по `topic` и allowlist отдела.
3. `room_generator.generate(...)`: планнер выбирает до 12 fixture-артефактов, привязанных к теме правила (9 опасных + 3 легитимных), детерминированно по `tenant_id/rule_id/попытка`.
4. `build_room_prompt` → LLM; системные поля (`topic`, `v`) добавляются после разбора JSON, лишние поля отбрасываются.
5. `validate_room` (L0–L3): схема и `v == 1`; `ref`/`kind`/`via`/глаголы/уроки; grounding по теме правила; цель не выполнена на старте, требует `report` опасного объекта, не заблокирована `hard`-ловушкой.
6. `room_fingerprint = sha256(topic + goal + refs)`; совпадение с комнатой тенанта — повод для повтора. Не более 3 попыток, затем детерминированная fallback-комната (без LLM).
7. `_generate_for_rule` собирает `Scenario` (`room`, `max_points = 10 + 2×diff`, `fingerprint`, `corpus_build_id`, `rule_snapshot`) и сохраняет со `status="generated"`.
8. Пачка: по правилу — `session.begin_nested()`, ошибки складываются в `errors[]` и не роняют остальные; fingerprint пополняется по ходу пачки.

Полный контракт и инварианты — ADR-0008. Поведение (`risk[]`, `benign`) живёт в метаданных артефакта, а не в комнате.

### 4.3 Попытки и движок событий

1. `POST /scenarios/{id}/attempts` → `scenario_attempts` с пустой лентой, `outcome=in_progress`.
2. `POST /attempts/{id}/events` с `{verb, obj}`: событие добавляется в ленту, движок пересчитывает попытку с нуля по всему журналу (идемпотентно, без скрытого состояния).
3. Движок: `hard`-риск → `compromised` (счёт ≤ 30% `max`), цель достигнута → `safe`/`recovered`, иначе `in_progress`. `blind` (−2) — если цель достигнута без `inspect`. Повторные `(verb, obj)` штрафуются один раз; после закрытия комнаты события не принимаются (`409`).
4. Ответ — `AttemptState`: исход, счёт, `blind`, мини-уроки (`lessons`) и лента с уровнем/штрафом. `goal`, `benign` и `risk[]` в ответ не попадают.

## 5. Данные

| Таблица | Ключевые поля | Связи |
|---|---|---|
| `documents` | `id`, `tenant_id`, `name`, `content_hash`, `size_bytes`, `rule_count`, `status`, `created_at`, `deleted_at` | — |
| `security_rules` | `id`, `tenant_id`, `document_id`, `description`, `topic`, `audience` (JSON), `content_hash`, `created_at`, `deleted_at` | `document_id → documents.id ON DELETE CASCADE` |
| `departments` | `id`, `tenant_id`, `name`, `allowed_topics` (JSON), `created_at` | `UNIQUE(tenant_id, name)` |
| `scenarios` | `id`, `tenant_id`, `title`, `topic`, `room` (JSON), `max_points`, `diff`, `fingerprint`, `corpus_build_id`, `rule_snapshot` (JSON), `department`, `status`, `created_at/updated_at`, `deleted_at` | FK нет: правило определяется `rule_snapshot.id` |
| `scenario_attempts` | `id`, `tenant_id`, `scenario_id`, `employee_id`, `events` (JSON), `outcome`, `score`, `max_points`, `lessons` (JSON), `started_at`, `finished_at` | `scenario_id → scenarios.id ON DELETE CASCADE` |

- Индексы: `documents(tenant_id, status, deleted_at)`, `security_rules(tenant_id, document_id, content_hash, deleted_at)`, `departments(tenant_id)`, `scenarios(tenant_id, status, topic, fingerprint, deleted_at)`, `scenario_attempts(tenant_id, employee_id)`, `scenario_attempts(scenario_id)`.
- Связь сценария с правилом хранится только в `rule_snapshot.id` (колонки `rule_id` нет — это было дублирование). Выборка «сценарии правила» и скрытие при удалении правила идут по JSON; expression index по `rule_snapshot->>'id'` не ставим до появления объёма (M6+).
- Миграции: `0001`…`0014` (head — `0014_room_contract`). `init.sql` дублирует DDL для первого старта контейнера и должен совпадать с ORM.
- Строки `scenarios`, созданные до `0014`, имеют `room = NULL` и приложением не читаются (колонки плоского формата удалены); они не удаляются автоматически.
- Векторного стора и `pg_trgm` нет: поиск по чанкам удалён вместе с хранением чанков.
- Удаление мягкое: `deleted_at` у документов, правил и сценариев; строки остаются для аналитики и истории сотрудника. Нормальные запросы фильтруют `deleted_at IS NULL`, аналитика использует `include_deleted=True`.

## 6. LLM-контур

| Класс | Назначение |
|---|---|
| `LLMProvider` | Абстракция: `generate()`, `is_available()` |
| `OpenAICompatibleProvider` | `/chat/completions` по HTTP; используется для `ollama` и `openai` |
| `VLLMProvider` | То же, но `model` в payload = имя LoRA (`secpol`); retry только на `ConnectError/ConnectTimeout` при прогреве vLLM |
| `get_llm_provider(settings)` | `vllm` → `VLLMProvider`, `ollama` → `OpenAICompatibleProvider(ollama_base_url)`, `openai` → `OpenAICompatibleProvider(llm_base_url, api_key)` |

Настройки (`Settings`): `llm_backend`, `vllm_base_url`, `vllm_lora_model`, `ollama_base_url`, `llm_base_url`, `llm_model`, `llm_api_key` (env: `LLM_API_KEY` или `OPENAI_API_KEY`), `llm_temperature`, `llm_num_ctx`, `llm_timeout`, `lora_strict`.

Docker Compose (`docker-compose.yaml`, корень):

| Сервис | Профиль | Порты | Особенности |
|---|---|---|---|
| `db` | всегда | `5432:5432` | `pgdata`, `init.sql`, healthcheck `pg_isready` |
| `backend` | всегда | `8000:8000` | зависит только от `db`; `env_file: .env`; `./backend:/app` |
| `vllm` | `gpu`, `low-vram` | `18001:8001` | `./llms:/llms`, `hf_cache`, `--enable-lora --lora-modules secpol=...` |
| `ollama` | `cpu` | `11434:11434` | `ollama_models` |

Внутри compose-сети backend обращается к `http://vllm:8001/v1` / `http://ollama:11434/v1`; снаружи — `localhost:18001` / `localhost:11434`.

## 7. API

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/health` | Liveness |
| `POST` | `/api/v1/documents/upload` | Загрузка и обработка документа (201) |
| `GET` | `/api/v1/documents/{id}` | Метаданные документа |
| `DELETE` | `/api/v1/documents/{id}` | Мягкое удаление документа, его правил и сценариев |
| `GET` | `/api/v1/rules` | Список правил тенанта (`topic`, `document_id`, `limit`, `offset`) |
| `GET` | `/api/v1/rules/{id}` | Правило |
| `DELETE` | `/api/v1/rules/{id}` | Мягкое удаление правила и его сценариев |
| `POST` | `/api/v1/scenarios/generate` | Комната по одному правилу (201, полный `Scenario`) |
| `POST` | `/api/v1/scenarios/generate-all` | Пачка по правилам отдела (201) |
| `GET` | `/api/v1/scenarios` | Публичный список комнат |
| `GET` | `/api/v1/scenarios/{id}` | Публичная комната: `title`, `brief`, `objs`, без `goal`/`risk` |
| `POST` | `/api/v1/scenarios/{id}/attempts` | Начать попытку сотрудника (201) |
| `DELETE` | `/api/v1/scenarios/{id}` | Мягкое удаление сценария |
| `GET` | `/api/v1/attempts` | Список попыток (`tenant_id`, `employee_id`, `scenario_id`) |
| `GET` | `/api/v1/attempts/{id}` | Состояние попытки |
| `POST` | `/api/v1/attempts/{id}/events` | Действие `(verb, obj)` → пересчитанное состояние |

## 8. Конфигурация и окружение

- `.env`, `.env.example`, `docker-compose.yaml` — в корне репозитория. `Settings` читает `env_file=_PROJECT_ROOT / ".env"`; приоритет: OS env → `.env` → дефолты `config.py`.
- `llms/base/Qwen2.5-7B-Instruct` и `llms/adapters/qwen2.5-7b-instruct-secpol-lora` — веса, монтируются в vLLM; backend их не читает.
- `backend/Dockerfile`, `backend/requirements.txt`, `backend/requirements-dev.txt` (ruff), `backend/ruff.toml`, `backend/pytest.ini` (`asyncio_mode=auto`), `backend/alembic.ini`.

## 9. Тесты и CI

Тесты: `tests/conftest.py` (SQLite + `Settings()`), `fakes.py` (`FakeLLMProvider`, валидная комната), `test_goals`, `test_room_validators`, `test_room_scoring`, `test_room_dedup`, `test_room_pipeline`, `test_scenario_service`, `test_attempts`, `test_security_rule_repository`, `test_department_repository`, `test_scenario_context`, `test_session_manager`, `test_chunking`, `test_parsers`, `test_ocr`, `test_text_repair`, `test_validator`, `test_soft_delete`.

CI (`.github/workflows/ci.yml`, ADR-0006): `lint` (ruff, узкий набор правил), `test` (pytest), `compose` (валидация трёх профилей), `migrations` (ровно одна head), `docker` (сборка образа без push). CD нет.

## 10. Безопасность и мультиарендность

Сейчас: `tenant_id` и `employee_id` приходят **от клиента** (`Form`/`Query`/тело запроса), аутентификации нет, CORS `allow_origins=["*"]` с пометкой TODO. Это осознанно зафиксированный долг: ADR-0004 вводит серверные сессии и идентичность только из сессии, `backlog_security.md` пп. 8–14 — остальной контур.

## 11. Технический долг и расхождения

| # | Проблема | Следствие |
|---|---|---|
| 1 | Нет таймаута попытки и исхода `timeout` | попытка остаётся `in_progress`, пока клиент её не закроет; таймаут появится вместе с виртуальным днём (M7) |
| 2 | `POST /generate` отдаёт полный `Scenario` с `goal` | эндпоинт операторский; после M3 закрывается ролью админа |
| 3 | `tenant_id` и `employee_id` из запроса, нет auth | IDOR между арендаторами (ADR-0004) |
| 4 | `CORS allow_origins=["*"]` | несовместимо с cookie-сессиями и production |
| 5 | `init.sql` и ORM поддерживаются вручную | риск расхождения DDL |
| 6 | Soft delete без restore-эндпоинта | восстановление только SQL (осознанно отложено) |
| 7 | Сценарии до миграции `0014` имеют `room = NULL` | не читаются и не удаляются автоматически; удалить вручную |
| 8 | Дедуп структурный, без эмбеддингов | перефразированная комната из других артефактов не отсекается (M9) |
| 9 | Поиск сценариев по правилу идёт по `rule_snapshot->>'id'` без индекса | seq scan на больших объёмах; expression index — при объёме M6+ |

## 12. Ссылки

- Решения: `docs/adr/` (0001 — история графа, 0007 — история комнаты, 0008 — актуальный контракт v1).
- План: `docs/plan-schedule.md` (M0–M11, гейты, порядок урезания).
- Безопасность: `backlog_security.md`, `docs/threat-model.md`.
- CI: `docs/ci.md`.
