"""rule scenario intent

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-17

Adds ``security_rules.intent`` — the resolved scenario intent (see
``app/core/intents.py``). Classification is done once per rule and cached here;
``NULL`` means "not classified yet".
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE security_rules ADD COLUMN IF NOT EXISTS intent VARCHAR(64)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE security_rules DROP COLUMN IF EXISTS intent")
