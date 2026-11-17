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
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS security_rules (
    id           VARCHAR(36)  PRIMARY KEY,
    tenant_id    VARCHAR(255) NOT NULL,
    document_id  VARCHAR(36)  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    description  TEXT         NOT NULL,
    topic        VARCHAR(64)  NOT NULL,
    intent       VARCHAR(64),
    audience     JSON         NOT NULL DEFAULT '[]'::json,
    content_hash VARCHAR(64)  NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
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
    id              VARCHAR(36)  PRIMARY KEY,
    tenant_id       VARCHAR(255) NOT NULL,
    title           VARCHAR(255) NOT NULL,
    topic           VARCHAR(64)  NOT NULL,
    room            JSON,
    max_points      INTEGER      NOT NULL DEFAULT 0,
    diff            INTEGER      NOT NULL DEFAULT 1,
    fingerprint     VARCHAR(64)  NOT NULL DEFAULT '',
    corpus_build_id VARCHAR(64)  NOT NULL DEFAULT '',
    rule_snapshot   JSON,
    department      VARCHAR(255),
    status          VARCHAR(16)  NOT NULL DEFAULT 'generated',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS scenario_attempts (
    id          VARCHAR(36)  PRIMARY KEY,
    tenant_id   VARCHAR(255) NOT NULL,
    scenario_id VARCHAR(36)  NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    employee_id VARCHAR(255) NOT NULL,
    events      JSON         NOT NULL DEFAULT '[]',
    outcome     VARCHAR(16)  NOT NULL DEFAULT 'in_progress',
    score       INTEGER,
    max_points  INTEGER      NOT NULL,
    lessons     JSON         NOT NULL DEFAULT '[]',
    started_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_documents_tenant_id      ON documents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_documents_status         ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_tenant_deleted ON documents (tenant_id, deleted_at);

CREATE INDEX IF NOT EXISTS idx_security_rules_tenant_id           ON security_rules (tenant_id);
CREATE INDEX IF NOT EXISTS idx_security_rules_document_id         ON security_rules (document_id);
CREATE INDEX IF NOT EXISTS idx_security_rules_tenant_content_hash ON security_rules (tenant_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_security_rules_tenant_deleted      ON security_rules (tenant_id, deleted_at);

CREATE INDEX IF NOT EXISTS idx_departments_tenant_id ON departments (tenant_id);

CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_id      ON scenarios (tenant_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_status         ON scenarios (status);
CREATE INDEX IF NOT EXISTS idx_scenarios_topic          ON scenarios (topic);
CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_deleted ON scenarios (tenant_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_fingerprint ON scenarios (tenant_id, fingerprint);

CREATE INDEX IF NOT EXISTS idx_scenario_attempts_tenant_employee
    ON scenario_attempts (tenant_id, employee_id);
CREATE INDEX IF NOT EXISTS idx_scenario_attempts_scenario_id
    ON scenario_attempts (scenario_id);
