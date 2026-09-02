"""leadgen_form_questions — cached instant-form question definitions (labels for lead answers)

Revision ID: 0004_leadgen_form_questions
Revises: 0003_processed_inbound_page_id
Create Date: 2026-09-02

One row per form_id: the Graph `questions` array verbatim, so the resolver can
turn a lead's option keys (`budget_2`) into the labels the visitor actually
saw without a Graph read per lead. See meta_ads.ingest.form_answers.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_leadgen_form_questions"
down_revision: str | None = "0003_processed_inbound_page_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0001 creates every table from the live SQLAlchemy metadata, so a fresh
    # database already has this table; only databases migrated before the
    # model existed need the DDL.
    bind = op.get_bind()
    if sa.inspect(bind).has_table("leadgen_form_questions", schema="meta"):
        return
    op.create_table(
        "leadgen_form_questions",
        sa.Column("form_id", sa.String(64), nullable=False),
        sa.Column("page_id", sa.String(64), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("locale", sa.String(16), nullable=True),
        sa.Column("questions", JSONB(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("form_id"),
        schema="meta",
    )


def downgrade() -> None:
    op.drop_table("leadgen_form_questions", schema="meta")
