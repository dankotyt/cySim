"""remove document/chunk storage and flatten scenario steps into inline fields

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop document-derived storage (missing references first, then chunks).
    op.drop_index(
        "idx_missing_references_document_id", table_name="missing_references"
    )
    op.drop_table("missing_references")

    op.drop_index("idx_document_chunks_text_tsv", table_name="document_chunks")
    op.drop_index("idx_document_chunks_text_trgm", table_name="document_chunks")
    op.drop_index("idx_document_chunks_document_id", table_name="document_chunks")
    op.drop_index("idx_document_chunks_tenant_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    # Decouple security_rules from documents entirely.
    op.drop_constraint(
        "security_rules_document_id_fkey", "security_rules", type_="foreignkey"
    )
    op.drop_index("idx_security_rules_document_id", table_name="security_rules")
    op.drop_column("security_rules", "document_id")

    # Drop the documents table itself.
    op.drop_index("idx_documents_tenant_status", table_name="documents")
    op.drop_index("idx_documents_status", table_name="documents")
    op.drop_index("idx_documents_tenant_id", table_name="documents")
    op.drop_table("documents")

    # Flatten the nested steps list into inline single-step columns
    # (server defaults only backfill pre-existing rows).
    op.drop_column("scenarios", "steps")
    op.add_column(
        "scenarios",
        sa.Column("step_type", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "scenarios",
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "scenarios",
        sa.Column(
            "actions",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "scenarios",
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "scenarios",
        sa.Column("correct_action", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("scenarios", "correct_action")
    op.drop_column("scenarios", "feedback")
    op.drop_column("scenarios", "actions")
    op.drop_column("scenarios", "content")
    op.drop_column("scenarios", "step_type")
    op.add_column(
        "scenarios",
        sa.Column(
            "steps",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("idx_documents_status", "documents", ["status"])
    op.create_index(
        "idx_documents_tenant_status", "documents", ["tenant_id", "status"]
    )

    op.add_column(
        "security_rules",
        sa.Column("document_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "security_rules_document_id_fkey",
        "security_rules",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_security_rules_document_id", "security_rules", ["document_id"]
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_document_chunks_tenant_id", "document_chunks", ["tenant_id"]
    )
    op.create_index(
        "idx_document_chunks_document_id", "document_chunks", ["document_id"]
    )
    op.execute(
        "CREATE INDEX idx_document_chunks_text_trgm ON document_chunks "
        "USING gin (text gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX idx_document_chunks_text_tsv ON document_chunks "
        "USING gin (to_tsvector('russian', text))"
    )

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
