"""add departments table and scenario department/topics_used fields

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "allowed_topics",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_departments_tenant_id", "departments", ["tenant_id"])
    op.create_unique_constraint(
        "uq_departments_tenant_name", "departments", ["tenant_id", "name"]
    )

    op.add_column("scenarios", sa.Column("department", sa.String(255), nullable=True))
    op.add_column(
        "scenarios",
        sa.Column(
            "topics_used",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("scenarios", "topics_used")
    op.drop_column("scenarios", "department")

    op.drop_constraint(
        "uq_departments_tenant_name", "departments", type_="unique"
    )
    op.drop_index("idx_departments_tenant_id", table_name="departments")
    op.drop_table("departments")
