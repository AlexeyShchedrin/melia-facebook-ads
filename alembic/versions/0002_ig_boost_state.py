"""ig_boost_state — IG auto-boost ledger (media × zone)

Revision ID: 0002_ig_boost_state
Revises: 0001_initial_meta_schema
Create Date: 2026-07-10

One row per (IG media, zone): the boost decision, the created ad/creative,
and rotation timestamps. zone='' rows are media-level skips (lint / type /
music); see meta_ads.db.models.IgBoostState.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ig_boost_state"
down_revision: str | None = "0001_initial_meta_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0001 creates *all* tables straight from the live SQLAlchemy metadata, so
    # a fresh database already has ig_boost_state by the time 0002 runs. Only
    # databases migrated before this model existed actually need the DDL.
    bind = op.get_bind()
    if sa.inspect(bind).has_table("ig_boost_state", schema="meta"):
        return
    op.create_table(
        "ig_boost_state",
        sa.Column("media_id", sa.Text(), nullable=False),
        sa.Column("zone", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("lint_hits", sa.Text(), nullable=True),
        sa.Column("ad_id", sa.Text(), nullable=True),
        sa.Column("creative_id", sa.Text(), nullable=True),
        sa.Column("caption_excerpt", sa.Text(), nullable=True),
        sa.Column("media_product_type", sa.Text(), nullable=True),
        sa.Column("boosted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("media_id", "zone"),
        schema="meta",
    )


def downgrade() -> None:
    op.drop_table("ig_boost_state", schema="meta")
