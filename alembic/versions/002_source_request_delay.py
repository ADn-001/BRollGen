"""Add request_delay_seconds to media_sources

Revision ID: 002
Revises: 001
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_sources",
        sa.Column("request_delay_seconds", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("media_sources", "request_delay_seconds")
