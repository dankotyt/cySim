"""add content_hash unique constraint to security_rules

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "security_rules",
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
    )
    op.create_unique_constraint(
        "uq_security_rules_tenant_content",
        "security_rules",
        ["tenant_id", "content_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_security_rules_tenant_content", "security_rules", type_="unique"
    )
    op.drop_column("security_rules", "content_hash")
