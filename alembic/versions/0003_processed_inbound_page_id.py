"""processed_inbound.page_id — which Page's token resolves the lead (multi-page)

Revision ID: 0003_processed_inbound_page_id
Revises: 0002_ig_boost_state
Create Date: 2026-08-27

The webhook relay records page_id per lead; persisting it here lets the
lead_poll retry resolve a failed lead with the SAME Page token the live
attempt used. NULL = the primary Page (every pre-multi-page row).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_processed_inbound_page_id"
down_revision: str | None = "0002_ig_boost_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fresh databases get the column from the live metadata in 0001; only
    # databases migrated before the model gained page_id need the DDL.
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("processed_inbound", schema="meta")]
    if "page_id" in cols:
        return
    op.add_column(
        "processed_inbound",
        sa.Column("page_id", sa.String(64), nullable=True),
        schema="meta",
    )


def downgrade() -> None:
    op.drop_column("processed_inbound", "page_id", schema="meta")
