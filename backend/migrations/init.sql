-- CyberSim initial schema (PostgreSQL 16).
-- Executed automatically by the postgres container on first boot via
-- docker-entrypoint-initdb.d. Keep in sync with app/models/db_models.py.

CREATE TABLE IF NOT EXISTS documents (
    id           VARCHAR(36)  PRIMARY KEY,
    tenant_id    VARCHAR(255) NOT NULL,
    name         VARCHAR(255) NOT NULL,
    content_hash VARCHAR(64)  NOT NULL,
    size_bytes   INTEGER      NOT NULL DEFAULT 0,
    rule_count   INTEGER      NOT NULL DEFAULT 0,
    status       VARCHAR(16)  NOT NULL DEFAULT 'uploaded',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS security_rules (
    id          VARCHAR(36)  PRIMARY KEY,
    tenant_id   VARCHAR(255) NOT NULL,
    document_id VARCHAR(36)  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    description TEXT         NOT NULL,
    topic       VARCHAR(64)  NOT NULL,
    audience    JSON         NOT NULL DEFAULT '[]'::json,
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
    rule_id     VARCHAR(36)  REFERENCES security_rules(id) ON DELETE CASCADE,
    title       VARCHAR(255) NOT NULL,
    topic       VARCHAR(64)  NOT NULL,
    step_type   VARCHAR(64)  NOT NULL,
    content     TEXT         NOT NULL,
    actions     JSON         NOT NULL,
    feedback    TEXT         NOT NULL,
    scoring     JSON         NOT NULL,
    department  VARCHAR(255),
    status      VARCHAR(16)  NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_documents_tenant_id ON documents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_status     ON documents (status);

CREATE INDEX IF NOT EXISTS idx_security_rules_tenant_id   ON security_rules (tenant_id);
CREATE INDEX IF NOT EXISTS idx_security_rules_document_id ON security_rules (document_id);

CREATE INDEX IF NOT EXISTS idx_departments_tenant_id ON departments (tenant_id);

CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_id ON scenarios (tenant_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_rule_id   ON scenarios (rule_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_status    ON scenarios (status);
CREATE INDEX IF NOT EXISTS idx_scenarios_topic     ON scenarios (topic);
