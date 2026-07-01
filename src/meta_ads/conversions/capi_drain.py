"""Pipeline C — drain the CRM outbox into Meta Conversions API for CRM.

Reads the SAME `ads_contract.v_outbox` google-ads uses, but:

  🔴 INVARIANT (PLAN.md §5): only leads with a Meta `lead_id` are uploaded.
     No meta_lead_id → the lead did not originate on Meta → SKIP. We never use
     hashed email/phone to *decide* origin, because Meta matches PII
     aggressively and would falsely attribute Google/website leads to Meta,
     corrupting the very quality signal we're feeding back.

Meta origin is read from `ads_contract.v_leads_meta` (leads ⨝ lead_external_keys),
which exposes `meta_lead_id`. Idempotency: `meta.processed_outbox`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from meta_ads.channels.base import ConversionEvent
from meta_ads.channels.meta.conversions import MetaCapiUploader
from meta_ads.config import get_settings
from meta_ads.conversions.hashing import hash_email, hash_phone
from meta_ads.conversions.taxonomy import OUTBOX_KIND_SKIP, OUTBOX_KIND_TO_EVENT

logger = logging.getLogger(__name__)


@dataclass
class DrainOutcome:
    fetched: int = 0
    uploaded: int = 0
    skipped: int = 0
    deferred: int = 0
    failed: int = 0


@dataclass
class _Row:
    id: int
    kind: str
    lead_id: int | None
    payload: dict[str, Any]
    created_at: datetime


def _parse_dt(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if isinstance(value, datetime):
        return value
    return fallback


class CapiDrain:
    def __init__(self) -> None:
        self._settings = get_settings()
        # event_name -> (dataset_id, default_value_eur)
        self._dataset_map: dict[str, tuple[str, Decimal | None]] = {}

    async def _load_dataset_map(self, session: AsyncSession) -> None:
        rows = await session.execute(
            text(
                "SELECT event_name, dataset_id, default_value_eur "
                "FROM meta.conversion_dataset_map WHERE is_active = true"
            )
        )
        self._dataset_map = {r.event_name: (r.dataset_id, r.default_value_eur) for r in rows}

    async def _fetch_unprocessed(self, session: AsyncSession, limit: int) -> list[_Row]:
        rows = await session.execute(
            text(
                "SELECT o.id, o.kind, o.lead_id, o.payload, o.created_at "
                "FROM ads_contract.v_outbox o "
                "LEFT JOIN meta.processed_outbox p ON p.crm_outbox_id = o.id "
                "WHERE p.crm_outbox_id IS NULL "
                "ORDER BY o.created_at ASC LIMIT :lim"
            ),
            {"lim": limit},
        )
        return [
            _Row(id=r.id, kind=r.kind, lead_id=r.lead_id, payload=r.payload or {}, created_at=r.created_at)
            for r in rows
        ]

    async def _meta_attribution(self, session: AsyncSession, lead_id: int) -> dict[str, Any] | None:
        """Read from ads_contract.v_leads_meta. `meta_lead_id` NULL ⇒ not a Meta lead."""
        row = (
            await session.execute(
                text(
                    "SELECT meta_lead_id, email, phone, name, source_channel, status "
                    "FROM ads_contract.v_leads_meta WHERE lead_id = :id"
                ),
                {"id": lead_id},
            )
        ).first()
        if row is None:
            return None
        return {
            "meta_lead_id": row.meta_lead_id,
            "email": row.email,
            "phone": row.phone,
            "name": row.name,
            "source_channel": row.source_channel,
            "status": row.status,
        }

    async def _record(
        self, session: AsyncSession, row: _Row, *, meta_lead_id: str | None, error: str | None
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO meta.processed_outbox "
                "(crm_outbox_id, kind, lead_id, meta_lead_id, event_id, error, attempts, processed_at) "
                "VALUES (:id, :kind, :lead_id, :mlid, :eid, :err, 1, now()) "
                "ON CONFLICT (crm_outbox_id) DO UPDATE SET "
                "error = EXCLUDED.error, attempts = meta.processed_outbox.attempts + 1, processed_at = now()"
            ),
            {
                "id": row.id,
                "kind": row.kind,
                "lead_id": row.lead_id,
                "mlid": meta_lead_id,
                "eid": f"crm-outbox-{row.id}",
                "err": error,
            },
        )

    async def drain(self, *, limit: int = 100, dry_run: bool | None = None) -> DrainOutcome:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        if dry_run is None:
            dry_run = self._settings.fb_dry_run_default
        outcome = DrainOutcome()

        async with async_session_maker() as session:
            await self._load_dataset_map(session)
            rows = await self._fetch_unprocessed(session, limit)
            outcome.fetched = len(rows)

            # dataset_id -> list of (row, ConversionEvent)
            batches: dict[str, list[tuple[_Row, ConversionEvent]]] = {}

            for row in rows:
                if row.kind in OUTBOX_KIND_SKIP:
                    await self._record(session, row, meta_lead_id=None, error="skipped (kind)")
                    outcome.skipped += 1
                    continue

                mapped = OUTBOX_KIND_TO_EVENT.get(row.kind)
                if mapped is None:
                    await self._record(session, row, meta_lead_id=None, error=f"unknown kind {row.kind}")
                    outcome.skipped += 1
                    continue
                event_name, taxonomy_value = mapped

                attribution = (
                    await self._meta_attribution(session, row.lead_id) if row.lead_id else None
                ) or {}
                meta_lead_id = attribution.get("meta_lead_id")

                # 🔴 INVARIANT: no Meta lead_id ⇒ not our lead ⇒ never upload.
                if not meta_lead_id:
                    await self._record(session, row, meta_lead_id=None, error="not a meta lead (no lead_id)")
                    outcome.skipped += 1
                    continue

                dataset = self._dataset_map.get(event_name)
                if dataset is None:
                    # dataset/event not configured yet — leave UNPROCESSED to retry
                    # after `fb setup-datasets`.
                    outcome.deferred += 1
                    continue
                dataset_id, dataset_default = dataset

                email = attribution.get("email")
                phone = attribution.get("phone")
                event = ConversionEvent(
                    action_name=event_name,
                    event_time=_parse_dt(
                        row.payload.get("changed_at") or row.payload.get("submitted_at"),
                        row.created_at,
                    ),
                    value_eur=taxonomy_value if taxonomy_value is not None else dataset_default,
                    hashed_email=hash_email(email) if email else None,
                    hashed_phone=hash_phone(phone) if phone else None,
                    meta_lead_id=meta_lead_id,
                    lead_id=row.lead_id,
                    order_id=f"crm-outbox-{row.id}",
                )
                batches.setdefault(dataset_id, []).append((row, event))

            # Upload per dataset, then record each result. In dry_run we do NOT
            # record upload candidates as processed — a later live drain must
            # still pick them up (skips above ARE recorded: they're
            # deterministic classifications, independent of dry_run).
            for dataset_id, items in batches.items():
                if dry_run:
                    await MetaCapiUploader(dataset_id).upload(
                        [ev for _, ev in items], dry_run=True
                    )
                    outcome.deferred += len(items)
                    continue
                uploader = MetaCapiUploader(dataset_id)
                try:
                    await uploader.upload([ev for _, ev in items], dry_run=False)
                    ok, err = True, None
                except Exception as exc:  # noqa: BLE001
                    ok, err = False, str(exc)
                    logger.exception("CAPI upload failed for dataset %s", dataset_id)
                for row, ev in items:
                    if ok:
                        outcome.uploaded += 1
                    else:
                        outcome.failed += 1
                    await self._record(session, row, meta_lead_id=ev.meta_lead_id, error=err)

            await session.commit()

        logger.info(
            "capi drain: fetched=%d uploaded=%d skipped=%d deferred=%d failed=%d dry_run=%s",
            outcome.fetched, outcome.uploaded, outcome.skipped, outcome.deferred, outcome.failed, dry_run,
        )
        return outcome
