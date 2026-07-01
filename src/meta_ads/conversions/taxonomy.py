"""CRM outbox `kind` → Meta Conversions-API event name + default value (EUR).

Parallels google-ads' taxonomy but targets Meta's dataset events. These event
names must exist in the dataset (Events Manager) — created by `fb setup-datasets`.

`lead_submitted` is intentionally SKIPPED: the form submit happened on Meta, so
Meta already has it — re-sending would double-count. We only send the
down-funnel milestones that Meta cannot see (they happen in the CRM).
"""

from __future__ import annotations

from decimal import Decimal

# kind -> (meta_event_name, default_value_eur | None). None = use the real
# deal value from the lead when available.
OUTBOX_KIND_TO_EVENT: dict[str, tuple[str, Decimal | None]] = {
    "lifecycle_qualified": ("lead_qualified", Decimal("20.00")),
    # Sales offer sent — funnel position right after lead_qualified (user's
    # call, 2026-07-02); value between qualified (20) and meeting (50).
    "lifecycle_offer": ("lead_offer_sent", Decimal("30.00")),
    "lifecycle_meeting": ("lead_meeting_scheduled", Decimal("50.00")),
    "lifecycle_deposit": ("lead_deposit_paid", None),
    "lifecycle_contract": ("lead_contract_signed", None),
    "lifecycle_paid": ("lead_paid", None),
}

# Kinds we knowingly skip (record processed, never upload).
OUTBOX_KIND_SKIP: frozenset[str] = frozenset({"lead_submitted", "lifecycle_negotiation"})
