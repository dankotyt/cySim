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
    attack_type  VARCHAR(64)  NOT NULL,
    source       VARCHAR(255) NOT NULL,
    page         INTEGER      NOT NULL DEFAULT 1,
    score        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    content_hash VARCHAR(64)  NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_security_rules_tenant_content_attack_type UNIQUE (tenant_id, content_hash, attack_type)
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
CREATE INDEX IF NOT EXISTS idx_security_rules_attack_type ON security_rules (attack_type);

CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_id   ON scenarios (tenant_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_status      ON scenarios (status);
CREATE INDEX IF NOT EXISTS idx_scenarios_attack_type ON scenarios (attack_type);
