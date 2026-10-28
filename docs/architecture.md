## Модули backend/app

| Модуль | Ответственность |
|---|---|
| `api/v1/documents.py` | Эндпоинты `/upload`, `/process`, `/search`, `/missing-references` (GET/DELETE), `/{id}` |
| `api/v1/scenarios.py` | Эндпоинты `/generate`, `/generate-all`, `/{scenario_id}` (GET/DELETE), листинг |
| `core/config.py` | Pydantic Settings, `.env`, `DEFAULT_TENANT_ID` |
| `core/topics.py` | Единый controlled vocabulary: `ALLOWED_TOPICS`, `ATTACK_TYPES`, `AttackType`, `ATTACK_TYPE_TOPICS` |
| `core/database.py` | Подключение к PostgreSQL |
| `core/logging.py` | Централизованный логгер |
| `models/document.py` | `Document`, `Chunk`, `SearchResult`, `SecurityRule`, `MissingReference` |
| `models/scenario.py` | `Scenario`, `GenerateScenarioRequest`, `BatchGenerateRequest`/`Response` |
| `models/department.py` | `Department` (allowed_topics) |
| `models/db_models.py` | ORM: documents, document_chunks, security_rules, missing_references, departments, scenarios |
| `repositories/document_repository.py` | Async CRUD документов |
| `repositories/document_chunk_repository.py` | Async CRUD чанков + поиск по `pg_trgm` similarity |
| `repositories/security_rule_repository.py` | Async CRUD правил + `list_by_topics` |
| `repositories/department_repository.py` | Async CRUD отделов + `get_or_create_default` |
| `repositories/scenario_repository.py` | Async CRUD сценариев |
| `repositories/missing_reference_repository.py` | Async CRUD missing references |
| `services/document_service.py` | Пайплайн: ingest → parse → chunk → store → structure → search |
| `services/document_validator.py` | MIME + объём |
| `services/rule_structurer.py` | LLM-структурирование чанков в правила (текстовая дедупликация) |
| `services/scenario_context.py` | `SecurityRule` → текст промпта |
| `services/scenario_service.py` | Генерация сценариев: SQL-фильтр по topic + отделу |
| `services/llm_provider.py` | Async Ollama (Qwen3) + OpenAI-compatible |
| `services/session_manager.py` | Бюджетирование контекста LLM-сессии (anchor + сброс) |
| `utils/parsers.py` | PDF/DOCX/TXT + OCR + mojibake fix |
| `utils/chunking.py` | `RecursiveCharacterTextSplitter` |
| `utils/llm_json.py` | Парсинг JSON из ответов LLM (fences-tolerant) |
| `utils/ocr.py` | pytesseract fallback |
| `utils/text_repair.py` | Восстановление cp1251-mojibake |
| `main.py` | FastAPI entrypoint + CORS + lifespan + exception handlers |

## Пайплайн

1. **Ingest** — загрузка (PDF/DOCX/TXT), оригинал на диск.
2. **Parse** — `parse_file` (pypdf / python-docx / txt), `clean_text`, mojibake fix.
3. **Chunk** — `RecursiveCharacterTextSplitter` по страницам.
4. **Store** — чанки в `document_chunks` (PostgreSQL).
5. **Structure** — `RuleStructurer` (LLM, async) извлекает `SecurityRule`; текстовая дедупликация; правила в `security_rules`.
6. **Search** — `pg_trgm.similarity` по `document_chunks`, порог `min_search_score`.
7. **Scenario** — `ScenarioService` выбирает правила SQL-фильтром: `topic ∈ ATTACK_TYPE_TOPICS[attack_type]` и `topic ∈ department.allowed_topics`, затем LLM генерирует сценарий.

## Хранение

- Правила и чанки — **только PostgreSQL** (таблицы `security_rules`, `document_chunks`). Внешнего векторного стора нет.
- Отделы — таблица `departments` (`allowed_topics`, JSONB). Отдел `default` создаётся лениво и разрешает все `ALLOWED_TOPICS`.
- Поиск чанков — расширение `pg_trgm` (создаётся миграцией `0008`).

**Тесты:** `tests/` (pytest, `asyncio_mode = auto`). Фикстуры: `conftest.py`, `fakes.py` (`FakeLLMProvider`).

**Инфраструктура:** `Dockerfile`, `requirements.txt`, `migrations/init.sql` (DDL + `pg_trgm`), `docker-compose.yaml` (Postgres + Ollama/Qwen3).
