"""drop scenario context/correct_action/topics_used, use topic

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # attack_type -> topic, and drop the fields that were flattened away from
    # the Scenario model (context, correct_action, topics_used, description).
    op.drop_index("idx_scenarios_attack_type", table_name="scenarios")
    op.alter_column("scenarios", "attack_type", new_column_name="topic")
    op.create_index("idx_scenarios_topic", "scenarios", ["topic"])

    op.drop_column("scenarios", "topics_used")
    op.drop_column("scenarios", "correct_action")
    op.drop_column("scenarios", "context")
    op.drop_column("scenarios", "description")


def downgrade() -> None:
    op.add_column(
        "scenarios",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.add_column(
        "scenarios",
        sa.Column(
            "context",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "scenarios",
        sa.Column("correct_action", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "scenarios",
        sa.Column(
            "topics_used",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )

    op.drop_index("idx_scenarios_topic", table_name="scenarios")
    op.alter_column("scenarios", "topic", new_column_name="attack_type")
    op.create_index("idx_scenarios_attack_type", "scenarios", ["attack_type"])
