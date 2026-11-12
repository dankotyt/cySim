# Архитектура CyberSim

Документ фиксирует **текущее состояние** (as-is) и целевые решения, принятые в ADR. Если код и ADR расходятся — это технический долг, он перечислен в §11.

Дата обновления: 2026-11-12.

## 1. Что реализовано сейчас

| Реализовано | Не реализовано (план) |
|---|---|
| FastAPI backend: загрузка документов → извлечение правил → генерация сценариев | SPA-кабинет сотрудника/админа (ADR-0003) |
| PostgreSQL: `documents`, `security_rules`, `departments`, `scenarios` | Песочница и персональное состояние (ADR-0002) |
| LLM только по HTTP: vLLM (LoRA `secpol`) или Ollama/OpenAI | Веб-корпус, `site-service`, браузер (ADR-0005) |
| CI на GitHub Actions (5 job'ов) | Движок «комнат», попытки, баллы (ADR-0007) |
| Локальный тест-UI `upload.html` | Аутентификация, роли, мультиарендность из сессии (ADR-0004) |

Backend — модульный монолит: API → сервисы → репозитории → ORM. Отдельного фронтенда и отдельных сервисов пока нет.

## 2. Компоненты

```
клиент (upload.html / будущая SPA)
        │ HTTP
        ▼
┌──────────────────────────┐        ┌───────────────────────────┐
│ backend (FastAPI :8000)  │───────▶│ PostgreSQL 16 (:5432)     │
│ API → services → repos   │        │ 4 таблицы, Alembic        │
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
| `api/v1/scenarios.py` | `POST /generate`, `POST /generate-all`, `GET /{id}`, `GET` (список), `DELETE /{id}` |
| `core/config.py` | `Settings` (pydantic-settings), `.env` в корне репозитория, `DEFAULT_TENANT_ID` |
| `core/topics.py` | Единый словарь `ALLOWED_TOPICS` (18 тем) |
| `core/database.py` | Async engine и фабрика сессий (asyncpg) |
| `core/logging.py` | Централизованная настройка логов |
| `models/document.py` | `Document`, `UploadResponse`, `SecurityRule`, `DeleteResponse` (+ мёртвые DTO, §11) |
| `models/scenario.py` | `Scenario`, `ScenarioAction`, `ScenarioScoring`, `ScenarioStepType`, запросы/ответы генерации |
| `models/department.py` | `Department.allowed_topics` |
| `models/db_models.py` | ORM: `documents`, `security_rules`, `departments`, `scenarios` |
| `repositories/document_repository.py` | CRUD метаданных документа |
| `repositories/security_rule_repository.py` | Создание пачкой, выборки по тенанту/темам/фильтрам, удаление |
| `repositories/department_repository.py` | CRUD отделов, `get_or_create_default` |
| `repositories/scenario_repository.py` | CRUD сценариев, выборка по правилу |
| `repositories/missing_reference_repository.py` | Мёртвый модуль (§11) |
| `services/document_service.py` | Пайплайн загрузки: validate → parse → chunk → structure → rules → metadata |
| `services/document_validator.py` | MIME (libmagic), расширение, объём, минимум текста/чанков |
| `services/rule_structuring/` | LoRA-структурирование: `vocab`, `prompts`, `filters`, `structurer` |
| `services/scenario_context.py` | `SecurityRule` → текстовый блок промпта |
| `services/scenario_prompts.py` | Системный промпт и few-shot для генерации сценария |
| `services/scenario_service.py` | Выбор правил (topic + отдел), вызов LLM, валидация JSON, сохранение |
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
6. `security_rules.create_many` → правила с `document_id`.
7. `documents.status=processed`, `rule_count=N`; при исключении — `status=failed`, ошибка пробрасывается как `ProcessingError`.

Содержимое и чанки в БД **не сохраняются**.

### 4.2 Генерация сценариев (текущая реализация)

1. `POST /generate` (одно правило) или `/generate-all` (пачка).
2. Отдел → `allowed_topics`; правила фильтруются по `tenant_id`, затем по `topic` и allowlist отдела.
3. `build_scenario_context` + `build_scenario_prompt` → `get_llm_provider(settings).generate(...)`.
4. `_generate_with_retry`: одна повторная попытка при невалидном JSON.
5. `_scenario_from_raw` собирает плоский `Scenario`: `title/topic/step_type/content/actions/feedback/scoring`; репозиторий сохраняет его со `status="generated"`.
6. Пачка: по правилу — `session.begin_nested()`, ошибки складываются в `errors[]` и не роняют остальные.

Текущий сценарий — **один decision point** (`step_type` ∈ `email_view | phone_call | usb_insert | web_page | search_result`).

### 4.3 Целевой контракт (ADR-0007, не реализован)

Сценарий становится «комнатой»:

```json
{"v": 4, "objs": [{"id": "m1", "kind": "email", "ref": "c2411:email:em-0042"}],
 "goal": "report(m1)", "extra": [{"on": "reply", "obj": "m1", "level": "soft", "pen": 2, "lesson": "L_REPLY_TO"}]}
```

Поведение (`risk[]`, `benign`) живёт в метаданных артефакта корпуса; движок потребляет события `(действие, объект)`, `hard`-ловушка необратима, `soft` — штраф и продолжение. Валидация L0–L3: схема, ссылки и глаголы, grounding, достижимость цели. Требуется миграция `scenarios.room JSONB` и таблица попыток.

## 5. Данные

| Таблица | Ключевые поля | Связи |
|---|---|---|
| `documents` | `id`, `tenant_id`, `name`, `content_hash`, `size_bytes`, `rule_count`, `status`, `created_at` | — |
| `security_rules` | `id`, `tenant_id`, `document_id`, `description`, `topic`, `audience` (JSON), `created_at` | `document_id → documents.id ON DELETE CASCADE` |
| `departments` | `id`, `tenant_id`, `name`, `allowed_topics` (JSON), `created_at` | `UNIQUE(tenant_id, name)` |
| `scenarios` | `id`, `tenant_id`, `rule_id`, `title`, `topic`, `step_type`, `content`, `actions` (JSON), `feedback`, `scoring` (JSON), `department`, `status`, `created_at/updated_at` | `rule_id → security_rules.id ON DELETE CASCADE` (nullable) |

- Индексы: `documents(tenant_id, status)`, `security_rules(tenant_id, document_id)`, `departments(tenant_id)`, `scenarios(tenant_id, rule_id, status, topic)`.
- Миграции: `0001`…`0012` (head — `0012_scenario_topic_remove_context`). `init.sql` дублирует DDL для первого старта контейнера и должен совпадать с ORM.
- Векторного стора и `pg_trgm` нет: поиск по чанкам удалён вместе с хранением чанков.
- `scenarios.rule_id ON DELETE CASCADE` — известный риск потери истории (см. §11).

## 6. LLM-контур

| Класс | Назначение |
|---|---|
| `LLMProvider` | Абстракция: `generate()`, `is_available()` |
| `OpenAICompatibleProvider` | `/chat/completions` по HTTP; используется для `ollama` и `openai` |
| `VLLMProvider` | То же, но `model` в payload = имя LoRA (`secpol`); retry только на `ConnectError/ConnectTimeout` при прогреве vLLM |
| `OllamaLLMProvider` | Нативный клиент Ollama; **не используется** фабрикой (§11) |
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
| `DELETE` | `/api/v1/documents/{id}` | Удаление документа (каскадом — правила и сценарии) |
| `GET` | `/api/v1/rules` | Список правил тенанта |
| `GET` | `/api/v1/rules/{id}` | Правило |
| `DELETE` | `/api/v1/rules/{id}` | Удаление правила (каскадом — сценарии) |
| `POST` | `/api/v1/scenarios/generate` | Сценарий по одному правилу (201) |
| `POST` | `/api/v1/scenarios/generate-all` | Пачка по правилам отдела (201) |
| `GET` | `/api/v1/scenarios` | Список сценариев |
| `GET` | `/api/v1/scenarios/{id}` | Сценарий (сейчас отдаёт `is_correct` и `points` — см. §11) |
| `DELETE` | `/api/v1/scenarios/{id}` | Удаление |

## 8. Конфигурация и окружение

- `.env`, `.env.example`, `docker-compose.yaml` — в корне репозитория. `Settings` читает `env_file=_PROJECT_ROOT / ".env"`; приоритет: OS env → `.env` → дефолты `config.py`.
- `llms/base/Qwen2.5-7B-Instruct` и `llms/adapters/qwen2.5-7b-instruct-secpol-lora` — веса, монтируются в vLLM; backend их не читает.
- `backend/Dockerfile`, `backend/requirements.txt`, `backend/requirements-dev.txt` (ruff), `backend/ruff.toml`, `backend/pytest.ini` (`asyncio_mode=auto`), `backend/alembic.ini`.

## 9. Тесты и CI

Тесты: `tests/conftest.py` (SQLite + `Settings()`), `fakes.py` (`FakeLLMProvider`), сервисы/репозитории/парсеры — `test_scenario_service`, `test_security_rule_repository`, `test_department_repository`, `test_scenario_context`, `test_scenario_prompts`, `test_session_manager`, `test_chunking`, `test_parsers`, `test_ocr`, `test_text_repair`, `test_validator`.

CI (`.github/workflows/ci.yml`, ADR-0006): `lint` (ruff, узкий набор правил), `test` (pytest), `compose` (валидация трёх профилей), `migrations` (ровно одна head), `docker` (сборка образа без push). CD нет.

## 10. Безопасность и мультиарендность

Сейчас: `tenant_id` приходит **от клиента** (`Form`/`Query`/тело запроса), аутентификации нет, CORS `allow_origins=["*"]` с пометкой TODO. Это осознанно зафиксированный долг: ADR-0004 вводит серверные сессии и `tenant_id` только из сессии, `backlog_security.md` пп. 8–14 — остальной контур.

## 11. Технический долг и расхождения

| # | Проблема | Следствие |
|---|---|---|
| 1 | `repositories/missing_reference_repository.py` импортирует удалённый `MissingReferenceORM` | модуль падает при импорте; мёртвый код |
| 2 | `OllamaLLMProvider` не используется фабрикой (ollama идёт через OpenAI-compatible) | мёртвый класс, лишняя зависимость |
| 3 | В `models/document.py` остались `ProcessRequest/Response`, `Chunk`, `SearchQuery/Result/Response`, `MetricsResponse` | мёртвые DTO без эндпоинтов |
| 4 | `Settings.lora_max_new_tokens` / `lora_max_input_length` больше не читаются | мёртвые настройки |
| 5 | `scenarios` — плоский одношаговый формат, ADR-0007 требует «комнату» | миграция и новый движок |
| 6 | `GET /scenarios/{id}` отдаёт `is_correct` и `points` | ответ читается в DevTools (ADR-0007 §public) |
| 7 | `tenant_id` из запроса, нет auth | IDOR между арендаторами (ADR-0004) |
| 8 | `rule_id ON DELETE CASCADE` | удаление документа уничтожает историю обучения |
| 9 | `CORS allow_origins=["*"]` | несовместимо с cookie-сессиями и production |
| 10 | `init.sql` и ORM поддерживаются вручную | риск расхождения DDL |

## 12. Ссылки

- Решения: `docs/adr/` (0001 — история графа, 0007 — актуальный контракт комнаты).
- План: `docs/plan-schedule.md` (M0–M9, гейты, порядок урезания).
- Безопасность: `backlog_security.md`, `docs/threat-model.md`.
- CI: `docs/ci.md`.
