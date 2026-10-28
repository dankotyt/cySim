"""link scenarios to a single rule and decouple rules from documents

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Decouple rules from their source document: deleting a document must keep
    # its rules (and the scenarios built from them).
    op.drop_constraint(
        "security_rules_document_id_fkey", "security_rules", type_="foreignkey"
    )
    op.alter_column(
        "security_rules",
        "document_id",
        existing_type=sa.String(36),
        nullable=True,
    )
    op.create_foreign_key(
        "security_rules_document_id_fkey",
        "security_rules",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Link each scenario to exactly one rule; deleting a rule cascades to its
    # scenarios.
    op.add_column(
        "scenarios",
        sa.Column("rule_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "scenarios_rule_id_fkey",
        "scenarios",
        "security_rules",
        ["rule_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_scenarios_rule_id", "scenarios", ["rule_id"])


def downgrade() -> None:
    op.drop_index("idx_scenarios_rule_id", table_name="scenarios")
    op.drop_constraint(
        "scenarios_rule_id_fkey", "scenarios", type_="foreignkey"
    )
    op.drop_column("scenarios", "rule_id")

    op.drop_constraint(
        "security_rules_document_id_fkey", "security_rules", type_="foreignkey"
    )
    op.alter_column(
        "security_rules",
        "document_id",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.create_foreign_key(
        "security_rules_document_id_fkey",
        "security_rules",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
