"""Initial schema — all tables

Revision ID: 001
Revises: None
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ffmpeg_path", sa.Text(), nullable=True),
        sa.Column("tmp_path", sa.Text(), nullable=True),
        sa.Column("realesrgan_path", sa.Text(), nullable=True),
        sa.Column("analysis_method", sa.String(20), nullable=False, server_default="algorithmic"),
    )
    # Seed the single-row settings record
    op.execute("INSERT INTO app_settings (id, analysis_method) VALUES (1, 'algorithmic')")

    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("provider_type", sa.String(50), nullable=False),
        # SECURITY: api_key stored as plain text in v1 — encrypt in v2
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
    )

    op.create_table(
        "media_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "niche_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resolution", sa.String(20), nullable=False, server_default="1920x1080"),
        sa.Column("min_resolution", sa.String(20), nullable=False, server_default="1920x1080"),
        sa.Column("aspect_fit", sa.String(20), nullable=False, server_default="box_zoom"),
        sa.Column("upscale_method", sa.String(20), nullable=False, server_default="lanczos"),
        sa.Column("multi_item_per_tag", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("dedupe_repeat_tags", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("default_item_count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("llm_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("llm_provider_id", sa.Integer(), sa.ForeignKey("llm_providers.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "profile_source_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("niche_profiles.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("media_sources.id"), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "profile_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("niche_profiles.id"), nullable=False),
        sa.Column("word", sa.String(200), nullable=False),
        sa.UniqueConstraint("profile_id", "word", name="uq_profile_tag"),
    )

    op.create_table(
        "global_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("word", sa.String(200), nullable=False, unique=True),
    )


def downgrade() -> None:
    op.drop_table("global_tags")
    op.drop_table("profile_tags")
    op.drop_table("profile_source_links")
    op.drop_table("niche_profiles")
    op.drop_table("media_sources")
    op.drop_table("llm_providers")
    op.drop_table("app_settings")
