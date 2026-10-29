"""reintroduce document metadata and audience on security rules

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reintroduce documents as metadata-only records (no content/chunk storage).
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rule_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("idx_documents_status", "documents", ["status"])

    # Rework security_rules: audience replaces title/section/linked_docs, and
    # document_id links each rule back to its source document.
    op.drop_column("security_rules", "linked_docs")
    op.drop_column("security_rules", "section")
    op.drop_column("security_rules", "title")
    op.add_column(
        "security_rules",
        sa.Column(
            "audience",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "security_rules",
        sa.Column("document_id", sa.String(36), nullable=False),
    )
    op.create_foreign_key(
        "security_rules_document_id_fkey",
        "security_rules",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "idx_security_rules_document_id", "security_rules", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_security_rules_document_id", table_name="security_rules")
    op.drop_constraint(
        "security_rules_document_id_fkey", "security_rules", type_="foreignkey"
    )
    op.drop_column("security_rules", "document_id")
    op.drop_column("security_rules", "audience")
    op.add_column(
        "security_rules",
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "security_rules",
        sa.Column("section", sa.Text(), nullable=False, server_default=""),
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

    op.drop_index("idx_documents_status", table_name="documents")
    op.drop_index("idx_documents_tenant_id", table_name="documents")
    op.drop_table("documents")
