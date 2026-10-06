# CyberSim — Document Analysis (RAG) Module

Transforms uploaded security documents (PDF, DOCX, TXT) into a structured vector
representation, enabling the scenario-generation module to retrieve relevant
security rules via semantic search.

## Pipeline

1. **Ingestion** — accepts single or batch uploads; originals are stored on disk.
2. **Parsing** — extracts and cleans text (PDF via `pypdf`, DOCX via `python-docx`, TXT directly).
3. **Chunking** — splits text into overlapping chunks with `RecursiveCharacterTextSplitter`,
   preserving `source`, `page`, and `chunk_index` metadata.
4. **Embedding** — `bge-m3` via a local Ollama instance, with a `sentence-transformers` fallback.
5. **Vector storage** — ChromaDB (remote server via `HttpClient`, or `PersistentClient` as fallback), one collection per tenant.
6. **Retrieval** — semantic search with top-K results and metadata filtering.

## Project structure

```
backend/
├── app/
│   ├── api/v1/documents.py           # HTTP endpoints (async)
│   ├── services/document_service.py  # RAG business logic + service layer (async)
│   ├── services/document_validator.py# MIME / volume / relevance validation
│   ├── repositories/document_repository.py  # async PostgreSQL CRUD
│   ├── core/config.py             # Environment-driven settings
│   ├── core/database.py           # Async engine + session dependency
│   ├── core/logging.py            # Logging configuration
│   ├── models/document.py         # Pydantic models
│   ├── models/db_models.py        # SQLAlchemy ORM models
│   ├── utils/parsers.py           # PDF / DOCX / TXT parsers
│   ├── utils/chunking.py          # Semantic chunking
│   ├── utils/embeddings.py        # Embedding providers
│   └── main.py                    # FastAPI entry point
├── migrations/                    # Alembic + init.sql (PostgreSQL schema)
├── tests/                         # pytest unit + integration tests
├── alembic.ini
├── requirements.txt
├── Dockerfile
├── docker-compose.yaml
└── .env.example
```

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Start Ollama and pull the embedding model

```bash
ollama pull bge-m3
```

The module falls back to `sentence-transformers` when Ollama is unavailable.
To enable that fallback, install it explicitly (it pulls in PyTorch, ~2 GB):

```bash
pip install "sentence-transformers>=3.0"
```

### 3. Configure (optional)

Copy `.env.example` to `.env` and adjust values, or set environment variables
directly. See the table below.

### 4. Run

```bash
uvicorn app.main:app --reload
```

The API is served at `http://127.0.0.1:8000` (docs at `/docs`).

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DATABASE_URL` | `postgresql+asyncpg://cybersim:changeme@localhost:5432/cybersim` | Async PostgreSQL connection string |
| `STORAGE_DIR` | `data/uploads` | Where uploaded originals are stored |
| `CHROMA_PERSIST_DIR` | `data/chroma` | ChromaDB persistent storage path (fallback) |
| `QUARANTINE_DIR` | `data/quarantine` | Where documents that fail validation are moved |
| `USE_CHROMA_SERVER` | `false` | Use a remote Chroma server instead of `PersistentClient` |
| `CHROMA_HOST` | `localhost` | Chroma server host |
| `CHROMA_PORT` | `8000` | Chroma server port |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama` or `sentence-transformers` |
| `EMBEDDING_MODEL` | `bge-m3` | Ollama model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `SENTENCE_TRANSFORMER_MODEL` | `BAAI/bge-m3` | Fallback model |
| `EMBEDDING_BATCH_SIZE` | `32` | Embedding batch size |
| `CHUNK_SIZE` | `2000` | Chunk size in characters (~500 tokens English) |
| `CHUNK_OVERLAP` | `200` | Chunk overlap in characters |
| `ALLOWED_EXTENSIONS` | `.pdf,.docx,.txt` | Accepted upload types |
| `MAX_UPLOAD_SIZE_MB` | `50` | Upload size limit |
| `DEFAULT_TENANT_ID` | `default` | Tenant used when none is supplied |
| `COLLECTION_PREFIX` | `cybersim` | Chroma collection name prefix |
| `MIN_DOCUMENT_CHARS` | `100` | Minimum characters required per document |
| `MIN_DOCUMENT_CHUNKS` | `1` | Minimum chunks required per document |
| `RELEVANCE_THRESHOLD` | `0.5` | Minimum cosine similarity to IS reference phrases |

> Chunk sizes are expressed in characters. For English text, ~4 characters ≈ 1 token,
> so the defaults map to roughly 500 tokens per chunk with a ~50-token overlap. Tune
> `CHUNK_SIZE`/`CHUNK_OVERLAP` for your language and model.

## API examples

### Upload (single or batch)

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents/upload" \
  -F "tenant_id=acme" \
  -F "files=@policy.pdf" \
  -F "files=@guidelines.docx"
```

```json
[
  {"document_id": "…", "filename": "policy.pdf", "status": "uploaded"},
  {"document_id": "…", "filename": "guidelines.docx", "status": "uploaded"}
]
```

### Process

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents/process" \
  -H "Content-Type: application/json" \
  -d '{"document_id": "…", "tenant_id": "acme"}'
```

### Get document info

```bash
curl "http://127.0.0.1:8000/api/v1/documents/{document_id}?tenant_id=acme"
```

### Search

```bash
curl "http://127.0.0.1:8000/api/v1/documents/search?q=rules%20regarding%20attachments&tenant_id=acme&top_k=5&filename=policy.pdf"
```

### Delete

```bash
curl -X DELETE "http://127.0.0.1:8000/api/v1/documents/{document_id}?tenant_id=acme"
```

## Database & migrations

The application uses SQLAlchemy 2.0 async + asyncpg. Two equivalent paths are
provided for schema creation:

```bash
# Option A: Alembic (recommended for ongoing migrations)
cd backend
alembic upgrade head

# Option B: one-shot DDL (also applied automatically by the postgres container)
psql "$DATABASE_URL" -f migrations/init.sql
```

> **ChromaDB is gone.** Chunks and rules are stored entirely in PostgreSQL
> (`document_chunks`, `security_rules`); there is no vector store. Any Chroma
> collections/data created by older versions live outside Alembic — deleting
> them is a separate ops step (`chroma_data` volume / `data/chroma` directory),
> not a database migration.

## Service layer

Other modules (e.g. scenario generation) consume `DocumentService` directly.
Methods are async and receive an `AsyncSession` (typically from `get_db`):

```python
from app.core.database import get_db
from app.services.document_service import DocumentService

service = DocumentService()

async def run(session) -> None:
    rules = await service.extract_rules("acme", query="attachment handling rules")
    # [SecurityRule(title=..., description=..., category=..., source=..., page=..., score=...)]
```

## Running tests

```bash
cd backend
pytest
```

Unit tests cover parsing, chunking, and embedding (with a deterministic fake
provider); integration tests exercise the API with `httpx`/`TestClient` and an
ephemeral in-memory Chroma client.

## Docker

```bash
docker build -t cybersim-document-analysis ./backend
docker run -p 8000:8000 --env OLLAMA_BASE_URL=http://host.docker.internal:11434 cybersim-document-analysis
```

For the heavy `sentence-transformers` fallback:

```bash
docker build --build-arg INSTALL_FALLBACK=true -t cybersim-document-analysis ./backend
```
