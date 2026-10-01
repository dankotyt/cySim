"""rename security_rules.category to attack_type

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "security_rules",
        "category",
        new_column_name="attack_type",
        existing_type=sa.String(64),
    )
    # 'general' was the keyword-classification default; attack_type is always
    # set explicitly, so drop the stale server default.
    op.alter_column("security_rules", "attack_type", server_default=None)

    op.drop_index("idx_security_rules_category", table_name="security_rules")
    op.create_index("idx_security_rules_attack_type", "security_rules", ["attack_type"])

    op.drop_constraint(
        "uq_security_rules_tenant_content", "security_rules", type_="unique"
    )
    op.create_unique_constraint(
        "uq_security_rules_tenant_content_attack_type",
        "security_rules",
        ["tenant_id", "content_hash", "attack_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_security_rules_tenant_content_attack_type",
        "security_rules",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_security_rules_tenant_content",
        "security_rules",
        ["tenant_id", "content_hash"],
    )

    op.drop_index("idx_security_rules_attack_type", table_name="security_rules")
    op.alter_column(
        "security_rules",
        "attack_type",
        new_column_name="category",
        existing_type=sa.String(64),
    )
    op.create_index("idx_security_rules_category", "security_rules", ["category"])
    op.alter_column(
        "security_rules", "category", server_default=sa.text("'general'")
    )
