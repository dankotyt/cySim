"""room contract v1 for scenarios and attempt event logs

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-16

Replaces the flat single-step scenario (``step_type``/``content``/``actions``/
``feedback``/``scoring``) with the room document of ADR-0008:

* ``scenarios.room`` — the whole contract JSON (objects, goal, brief, diff);
* ``scenarios.max_points``, ``diff``, ``fingerprint``, ``corpus_build_id`` —
  scalar copies used for scoring, filtering and duplicate detection;
* drops ``scenarios.rule_id``: the source rule is identified by
  ``rule_snapshot.id``, so the FK was a second copy of the same fact; lookups
  match on the JSON copy instead of an indexed column;
* ``scenario_attempts`` — one row per trainee attempt with its event log.

Scenarios generated before this revision keep their rows but have ``room`` set
to NULL; the application no longer lists or serves them, because the old columns
are gone. Nothing is deleted here on purpose — remove such rows manually if the
history is not needed.

Downgrade restores the old columns with empty defaults; room content is lost.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_SCENARIO_COLUMNS = (
    "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS room JSON",
    "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS max_points INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS diff INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS corpus_build_id VARCHAR(64) NOT NULL DEFAULT ''",
)

_OLD_SCENARIO_COLUMNS = (
    "step_type",
    "content",
    "actions",
    "feedback",
    "scoring",
)


def upgrade() -> None:
    for statement in _NEW_SCENARIO_COLUMNS:
        op.execute(statement)

    for column in _OLD_SCENARIO_COLUMNS:
        op.execute(f"ALTER TABLE scenarios DROP COLUMN IF EXISTS {column}")

    op.execute("DROP INDEX IF EXISTS idx_scenarios_rule_id")
    op.execute("ALTER TABLE scenarios DROP COLUMN IF EXISTS rule_id")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenarios_tenant_fingerprint "
        "ON scenarios (tenant_id, fingerprint)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scenario_attempts (
            id          VARCHAR(36)  PRIMARY KEY,
            tenant_id   VARCHAR(255) NOT NULL,
            scenario_id VARCHAR(36)  NOT NULL
                        REFERENCES scenarios(id) ON DELETE CASCADE,
            employee_id VARCHAR(255) NOT NULL,
            events      JSON         NOT NULL DEFAULT '[]',
            outcome     VARCHAR(16)  NOT NULL DEFAULT 'in_progress',
            score       INTEGER,
            max_points  INTEGER      NOT NULL,
            lessons     JSON         NOT NULL DEFAULT '[]',
            started_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenario_attempts_tenant_employee "
        "ON scenario_attempts (tenant_id, employee_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenario_attempts_scenario_id "
        "ON scenario_attempts (scenario_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scenario_attempts")
    op.execute("DROP INDEX IF EXISTS idx_scenarios_tenant_fingerprint")

    for column in ("room", "max_points", "diff", "fingerprint", "corpus_build_id"):
        op.execute(f"ALTER TABLE scenarios DROP COLUMN IF EXISTS {column}")

    op.execute(
        "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS step_type "
        "VARCHAR(64) NOT NULL DEFAULT 'email_view'"
    )
    op.execute(
        "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS content "
        "TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS actions "
        "JSON NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS feedback "
        "TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS scoring "
        "JSON NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS rule_id VARCHAR(36) "
        "REFERENCES security_rules(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenarios_rule_id "
        "ON scenarios (rule_id)"
    )
