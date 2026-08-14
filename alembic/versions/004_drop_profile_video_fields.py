"""Drop resolution/min_resolution/aspect_fit/upscale_method from niche_profiles

These fields only ever fed the video-stitching/upscale pipeline (ffmpeg
sweep, Real-ESRGAN, box_zoom/black_overlay filter graphs) that Phase 1
removed entirely — files are exported exactly as downloaded, with no
resize/crop/upscale step. The columns and their UI were left in place at
the time as a "harmless, no active use" cleanup deferral; this migration
finishes that cleanup now that the frontend no longer references them.

Revision ID: 004
Revises: 003
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires batch mode to drop columns (it has no native
    # ALTER TABLE ... DROP COLUMN prior to being routed through a
    # recreate-and-copy under the hood, which batch_alter_table handles).
    with op.batch_alter_table("niche_profiles") as batch_op:
        batch_op.drop_column("resolution")
        batch_op.drop_column("min_resolution")
        batch_op.drop_column("aspect_fit")
        batch_op.drop_column("upscale_method")


def downgrade() -> None:
    with op.batch_alter_table("niche_profiles") as batch_op:
        batch_op.add_column(
            sa.Column("resolution", sa.String(20), nullable=False, server_default="1920x1080")
        )
        batch_op.add_column(
            sa.Column("min_resolution", sa.String(20), nullable=False, server_default="1920x1080")
        )
        batch_op.add_column(
            sa.Column("aspect_fit", sa.String(20), nullable=False, server_default="box_zoom")
        )
        batch_op.add_column(
            sa.Column("upscale_method", sa.String(20), nullable=False, server_default="lanczos")
        )
