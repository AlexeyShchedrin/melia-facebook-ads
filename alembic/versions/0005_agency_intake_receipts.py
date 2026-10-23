"""Preserve project integer receipts and add agency UUID inquiry receipts.

Revision ID: 0005_agency_intake_receipts
Revises: 0004_leadgen_form_questions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0005_agency_intake_receipts"
down_revision: str | None = "0004_leadgen_form_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESULT_CHECK = """COALESCE(
    (result_kind IS NULL AND crm_lead_id IS NULL AND agency_inquiry_id IS NULL AND agency_lead_id IS NULL AND match_status IS NULL)
    OR ((result_kind = 'project' OR result_kind IS NULL) AND crm_lead_id > 0 AND agency_inquiry_id IS NULL AND agency_lead_id IS NULL AND match_status IS NULL)
    OR (result_kind = 'agency' AND crm_lead_id IS NULL AND agency_inquiry_id IS NOT NULL AND
        ((match_status = 'matched' AND agency_lead_id IS NOT NULL) OR (match_status IN ('conflict','unresolved') AND agency_lead_id IS NULL))), FALSE)"""


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("processed_inbound", schema="meta")}
    additions = [
        sa.Column("connection_key", sa.String(160), nullable=True),
        sa.Column("result_kind", sa.String(16), nullable=True),
        sa.Column("agency_inquiry_id", UUID(as_uuid=True), nullable=True),
        sa.Column("agency_lead_id", UUID(as_uuid=True), nullable=True),
        sa.Column("match_status", sa.String(16), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    ]
    for column in additions:
        if column.name not in columns:
            op.add_column("processed_inbound", column, schema="meta")
    op.execute("UPDATE meta.processed_inbound SET result_kind = 'project' WHERE crm_lead_id IS NOT NULL AND result_kind IS NULL")
    op.execute("UPDATE meta.processed_inbound SET delivered_at = processed_at WHERE crm_lead_id IS NOT NULL AND delivered_at IS NULL")
    checks = {c["name"] for c in sa.inspect(bind).get_check_constraints("processed_inbound", schema="meta")}
    if "ck_meta_inbound_result" not in checks:
        op.create_check_constraint("ck_meta_inbound_result", "processed_inbound", RESULT_CHECK, schema="meta")
    # The CRM can diagnose deliveries without reading tokens or personal fields.
    # Historical error strings are deliberately reduced to a category.
    op.execute("""CREATE OR REPLACE VIEW meta.v_inbound_delivery AS SELECT
        leadgen_id, form_id, page_id, connection_key, result_kind, crm_lead_id,
        agency_inquiry_id, agency_lead_id, match_status, attempts, processed_at, delivered_at,
        CASE WHEN error IS NULL THEN NULL
             WHEN error ~ '^(provider_http_[0-9]+_code_([0-9]+|unknown)|crm_http_[0-9]+|crm_meta_source_unmapped|crm_meta_source_disabled|crm_meta_contract_upgrade_required|crm_agency_intake_unavailable|crm_invalid_agency_intake|delivery_timeout|delivery_unavailable|invalid_delivery_contract|delivery_failed)$' THEN error
             ELSE 'legacy_delivery_error' END AS error
        FROM meta.processed_inbound""")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melia') THEN
            GRANT USAGE ON SCHEMA meta TO melia;
            GRANT SELECT ON meta.v_inbound_delivery TO melia;
        END IF;
    END $$""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM meta.processed_inbound WHERE agency_inquiry_id IS NOT NULL)")):
        raise RuntimeError("Agency receipts exist; restore a compatible worker instead of removing UUID receipts")
    op.execute("DROP VIEW IF EXISTS meta.v_inbound_delivery")
    op.drop_constraint("ck_meta_inbound_result", "processed_inbound", schema="meta", type_="check")
    for name in ["delivered_at", "match_status", "agency_lead_id", "agency_inquiry_id", "result_kind", "connection_key"]:
        op.drop_column("processed_inbound", name, schema="meta")
