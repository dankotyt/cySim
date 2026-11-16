"""rule snapshot, soft delete and rule de-duplication

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-13

Adds:
* ``documents.deleted_at`` / ``security_rules.deleted_at`` / ``scenarios.deleted_at``
  for soft deletion (rows stay for analytics);
* ``scenarios.rule_snapshot`` — immutable copy of the rule text;
* ``security_rules.content_hash`` — stable hash of (topic, normalised text) used
  for tenant-wide de-duplication, with a backfill for existing rows;
* drops the stale ``uq_security_rules_tenant_content_attack_type`` constraint
  left over from migration 0006 (it became ``(tenant_id, content_hash, topic)``
  after 0012 and rejected two same-topic rules because ``content_hash`` was
  always the empty default).

The statements use ``IF [NOT] EXISTS`` so the migration is also safe on a fresh
database created from ``init.sql``.
"""
import hashlib
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text or "").strip().casefold()


def _content_hash(topic: str, description: str) -> str:
    payload = f"{topic}\x1f{_normalise(description)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE security_rules ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
    )
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS rule_snapshot JSON")
    op.execute(
        "ALTER TABLE security_rules ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"
    )

    # The old constraint compares empty hashes; drop it before backfilling.
    op.execute(
        "ALTER TABLE security_rules "
        "DROP CONSTRAINT IF EXISTS uq_security_rules_tenant_content_attack_type"
    )
    op.execute(
        "ALTER TABLE security_rules "
        "DROP CONSTRAINT IF EXISTS uq_security_rules_tenant_content"
    )
    op.execute("ALTER TABLE security_rules ALTER COLUMN content_hash DROP DEFAULT")

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, topic, description FROM security_rules "
            "WHERE content_hash IS NULL OR content_hash = ''"
        )
    ).fetchall()
    for row in rows:
        connection.execute(
            sa.text("UPDATE security_rules SET content_hash = :hash WHERE id = :id"),
            {"hash": _content_hash(row.topic, row.description), "id": row.id},
        )

    op.execute(
        "ALTER TABLE security_rules ALTER COLUMN content_hash SET NOT NULL"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_tenant_deleted "
        "ON documents (tenant_id, deleted_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_rules_tenant_content_hash "
        "ON security_rules (tenant_id, content_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_rules_tenant_deleted "
        "ON security_rules (tenant_id, deleted_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_deleted "
        "ON scenarios (tenant_id, deleted_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_scenarios_tenant_deleted")
    op.execute("DROP INDEX IF EXISTS idx_security_rules_tenant_deleted")
    op.execute("DROP INDEX IF EXISTS idx_security_rules_tenant_content_hash")
    op.execute("DROP INDEX IF EXISTS idx_documents_tenant_deleted")

    op.execute("ALTER TABLE scenarios DROP COLUMN IF EXISTS rule_snapshot")
    op.execute("ALTER TABLE scenarios DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE security_rules DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS deleted_at")

    # `content_hash` is intentionally kept: it existed before 0013 on migrated
    # databases (migration 0006) and the stale constraint is not recreated.
