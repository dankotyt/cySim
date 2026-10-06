"""add document_chunks table with pg_trgm/to_tsvector search indexes

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

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
    # Trigram index for pg_trgm.similarity ranking.
    op.execute(
        "CREATE INDEX idx_document_chunks_text_trgm ON document_chunks "
        "USING gin (text gin_trgm_ops)"
    )
    # Full-text index for to_tsvector('russian', text).
    op.execute(
        "CREATE INDEX idx_document_chunks_text_tsv ON document_chunks "
        "USING gin (to_tsvector('russian', text))"
    )


def downgrade() -> None:
    op.drop_index(
        "idx_document_chunks_text_tsv", table_name="document_chunks"
    )
    op.drop_index(
        "idx_document_chunks_text_trgm", table_name="document_chunks"
    )
    op.drop_index("idx_document_chunks_document_id", table_name="document_chunks")
    op.drop_index("idx_document_chunks_tenant_id", table_name="document_chunks")
    op.drop_table("document_chunks")
