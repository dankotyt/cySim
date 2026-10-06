"""replace heuristic rule fields with LLM-structured fields

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the constraint and index tied to the removed fields.
    op.drop_constraint(
        "uq_security_rules_tenant_content_attack_type",
        "security_rules",
        type_="unique",
    )
    op.drop_index("idx_security_rules_attack_type", table_name="security_rules")

    # Drop RAG-era columns.
    op.drop_column("security_rules", "content_hash")
    op.drop_column("security_rules", "score")
    op.drop_column("security_rules", "attack_type")
    op.drop_column("security_rules", "page")
    op.drop_column("security_rules", "source")

    # Add LLM-structured columns (server defaults only backfill pre-existing rows).
    op.add_column(
        "security_rules",
        sa.Column("section", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "security_rules",
        sa.Column("topic", sa.String(64), nullable=False, server_default="other"),
    )
    op.add_column(
        "security_rules",
        sa.Column(
            "linked_docs",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )

    # Missing internal document references.
    op.create_table(
        "missing_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_missing_references_document_id", "missing_references", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_missing_references_document_id", table_name="missing_references")
    op.drop_table("missing_references")

    op.drop_column("security_rules", "linked_docs")
    op.drop_column("security_rules", "topic")
    op.drop_column("security_rules", "section")

    op.add_column(
        "security_rules",
        sa.Column("source", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "security_rules",
        sa.Column("page", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "security_rules",
        sa.Column("attack_type", sa.String(64), nullable=False, server_default="phishing"),
    )
    op.add_column(
        "security_rules",
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "security_rules",
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
    )

    op.create_index("idx_security_rules_attack_type", "security_rules", ["attack_type"])
    op.create_unique_constraint(
        "uq_security_rules_tenant_content_attack_type",
        "security_rules",
        ["tenant_id", "content_hash", "attack_type"],
    )
