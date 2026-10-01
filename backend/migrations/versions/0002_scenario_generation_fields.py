"""add scenario generation fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scenarios",
        sa.Column("attack_type", sa.String(64), nullable=False, server_default="phishing"),
    )
    op.add_column(
        "scenarios",
        sa.Column("context", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.add_column(
        "scenarios",
        sa.Column("steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "scenarios",
        sa.Column("scoring", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.create_index("idx_scenarios_attack_type", "scenarios", ["attack_type"])


def downgrade() -> None:
    op.drop_index("idx_scenarios_attack_type", table_name="scenarios")
    op.drop_column("scenarios", "scoring")
    op.drop_column("scenarios", "steps")
    op.drop_column("scenarios", "context")
    op.drop_column("scenarios", "attack_type")
