"""attempt outcome failed

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-17

A hard trap now ends the room with ``outcome='failed'`` and one point instead
of the old ``compromised``/30 % cap. Existing rows are rewritten so the ORM
can validate them against the new ``AttemptOutcome`` literal.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE scenario_attempts SET outcome = 'failed' "
        "WHERE outcome = 'compromised'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE scenario_attempts SET outcome = 'compromised' "
        "WHERE outcome = 'failed'"
    )
