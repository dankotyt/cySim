FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build toolchain (hnswlib) and libmagic (python-magic) for document validation.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Optional heavy fallback embedding backend. Build with:
#   docker build --build-arg INSTALL_FALLBACK=true -t cybersim-document-analysis .
ARG INSTALL_FALLBACK=false
RUN if [ "$INSTALL_FALLBACK" = "true" ]; then \
        pip install --no-cache-dir "sentence-transformers>=3.0"; \
    fi

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
