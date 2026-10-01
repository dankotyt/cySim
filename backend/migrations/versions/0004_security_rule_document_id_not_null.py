"""make security_rules.document_id not null

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Old code never set document_id; any leftover rows cannot be mapped back to
    # a document, so drop them (they are regenerated on the next reprocess).
    op.execute("DELETE FROM security_rules WHERE document_id IS NULL")
    op.alter_column(
        "security_rules",
        "document_id",
        existing_type=sa.String(36),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "security_rules",
        "document_id",
        existing_type=sa.String(36),
        nullable=True,
    )
