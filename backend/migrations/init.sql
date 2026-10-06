-- CyberSim initial schema (PostgreSQL 16).
-- Executed automatically by the postgres container on first boot via
-- docker-entrypoint-initdb.d. Keep in sync with app/models/db_models.py.

CREATE TABLE IF NOT EXISTS documents (
    id            VARCHAR(36)  PRIMARY KEY,
    tenant_id     VARCHAR(255) NOT NULL,
    filename      VARCHAR(255) NOT NULL,
    document_type VARCHAR(16)  NOT NULL,
    status        VARCHAR(16)  NOT NULL,
    file_path     TEXT         NOT NULL,
    size_bytes    INTEGER      NOT NULL DEFAULT 0,
    page_count    INTEGER      NOT NULL DEFAULT 0,
    chunk_count   INTEGER      NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    processed_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS security_rules (
    id           VARCHAR(36)  PRIMARY KEY,
    tenant_id    VARCHAR(255) NOT NULL,
    document_id  VARCHAR(36)  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    title        VARCHAR(255) NOT NULL,
    description  TEXT         NOT NULL,
    section      TEXT         NOT NULL,
    topic        VARCHAR(64)  NOT NULL,
    linked_docs  JSON         NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS missing_references (
    id          VARCHAR(36)  PRIMARY KEY,
    tenant_id   VARCHAR(255) NOT NULL,
    document_id VARCHAR(36)  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    reference   TEXT         NOT NULL,
    section     TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS departments (
    id             VARCHAR(36)  PRIMARY KEY,
    tenant_id      VARCHAR(255) NOT NULL,
    name           VARCHAR(255) NOT NULL,
    allowed_topics JSON         NOT NULL DEFAULT '[]'::json,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_departments_tenant_name UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS scenarios (
    id          VARCHAR(36)  PRIMARY KEY,
    tenant_id   VARCHAR(255) NOT NULL,
    title       VARCHAR(255) NOT NULL,
    description TEXT,
    attack_type VARCHAR(64)  NOT NULL DEFAULT 'phishing',
    context     JSON         NOT NULL,
    steps       JSON         NOT NULL,
    scoring     JSON         NOT NULL,
    department  VARCHAR(255),
    topics_used JSON         NOT NULL DEFAULT '[]'::json,
    status      VARCHAR(16)  NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_documents_tenant_id ON documents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_status     ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_tenant_status
    ON documents (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_security_rules_tenant_id ON security_rules (tenant_id);
CREATE INDEX IF NOT EXISTS idx_security_rules_document_id ON security_rules (document_id);

CREATE INDEX IF NOT EXISTS idx_missing_references_document_id ON missing_references (document_id);

CREATE INDEX IF NOT EXISTS idx_departments_tenant_id ON departments (tenant_id);

CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_id   ON scenarios (tenant_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_status      ON scenarios (status);
CREATE INDEX IF NOT EXISTS idx_scenarios_attack_type ON scenarios (attack_type);
