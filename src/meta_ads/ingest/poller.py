"""Pipeline B safety net — reconcile the leads the webhook never delivered.

The relay → resolver path is at-least-once only if Meta's webhook actually
arrives. It does not always: Meta gives up after its own retries, and a CRM
deploy 502s inbound webhooks for the length of the window. Nothing else
re-checked, and a lead that never lands is invisible — there is no row to alert
on, so the loss looks exactly like a quiet day.

Every 15 min this job therefore does two things:

  1. re-tries rows recorded WITHOUT a crm_lead_id, bounded by `attempts`. That
     makes a transient failure — or one a later deploy fixed — self-healing
     instead of terminal, which is what a 422 used to be.
  2. polls each active form's /leads and ingests any leadgen_id we hold no row
     for at all.

Both funnel through InboundResolver.ingest_and_record, so a reconciled lead is
byte-identical to a webhook-delivered one. meta.processed_inbound stays the
idempotency key throughout, and the resolver's advisory lock keeps this job from
racing the live path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from meta_ads.channels.meta.leadforms import list_forms
from meta_ads.channels.meta.leads import poll_form_leads
from meta_ads.config import get_settings
from meta_ads.ingest.resolver import _RESOLVE_LOCK_KEY, InboundResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FormPoll:
    """One planned form sweep."""

    form_id: str
    since_unix: int | None
    max_pages: int
    reason: str


@dataclass
class PollOutcome:
    forms_polled: int = 0
    recovered: int = 0
    retried: int = 0
    failed: int = 0

    @property
    def touched(self) -> int:
        return self.recovered + self.retried + self.failed


def plan_polls(
    forms: list[dict[str, Any]],
    our_counts: dict[str, int],
    *,
    now_unix: int,
    lookback_hours: int,
    deep_pages: int,
    max_pages: int,
) -> list[FormPoll]:
    """Decide which forms to sweep, and how far back to look.

    Meta's `leads_count` is a hint, never a gate. It excludes test leads, it races
    with leads arriving as we read it, and we have seen it report 0 for a form
    holding 203 leads — so gating the sweep on it would blind us to exactly the
    forms whose bookkeeping is broken. Every form that has ever taken a lead gets
    the routine window regardless.

    It is trustworthy in one direction: when Meta counts MORE than we hold,
    something may be missing, and a gap older than the routine window is worth
    scanning the newest pages for (Meta returns leads newest-first).
    """
    cutoff = now_unix - lookback_hours * 3600
    plans: list[FormPoll] = []
    for form in forms:
        form_id = str(form.get("id") or "")
        status = form.get("status")
        if not form_id or (status is not None and status != "ACTIVE"):
            continue
        theirs = form.get("leads_count")
        ours = our_counts.get(form_id, 0)
        if not theirs and not ours:
            continue  # a form that has never taken a lead — nothing to reconcile
        if isinstance(theirs, int) and theirs > ours:
            plans.append(
                FormPoll(form_id, None, deep_pages, f"meta says {theirs}, we hold {ours}")
            )
        else:
            plans.append(FormPoll(form_id, cutoff, max_pages, "routine"))
    return plans


class LeadPoller:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._resolver = InboundResolver()

    async def _our_counts(self, session: AsyncSession) -> dict[str, int]:
        rows = await session.execute(
            text(
                "SELECT form_id, count(*) FROM meta.processed_inbound "
                "WHERE form_id IS NOT NULL GROUP BY form_id"
            )
        )
        return {r[0]: r[1] for r in rows}

    async def _retryable(self, session: AsyncSession) -> list[tuple[str, str | None]]:
        """Rows that never reached the CRM and still have attempts left."""
        rows = await session.execute(
            text(
                "SELECT leadgen_id, form_id FROM meta.processed_inbound "
                "WHERE crm_lead_id IS NULL AND attempts < :max "
                "ORDER BY processed_at LIMIT :lim"
            ),
            {
                "max": self._settings.fb_lead_poll_max_attempts,
                "lim": self._settings.fb_lead_poll_retry_limit,
            },
        )
        return [(r[0], r[1]) for r in rows]

    async def _known(self, session: AsyncSession, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        rows = await session.execute(
            text("SELECT leadgen_id FROM meta.processed_inbound WHERE leadgen_id = ANY(:ids)"),
            {"ids": ids},
        )
        return {r[0] for r in rows}

    async def run(self) -> PollOutcome:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        outcome = PollOutcome()
        if not self._settings.fb_lead_poll_enabled:
            logger.debug("lead_poll disabled")
            return outcome

        # Phase 1 — read our side and Meta's side. No lock and no write, so the
        # live resolver keeps running while we do the slow Graph work.
        async with async_session_maker() as session:
            our_counts = await self._our_counts(session)
            retry = await self._retryable(session)

        plans = plan_polls(
            await list_forms(),
            our_counts,
            now_unix=int(datetime.now(UTC).timestamp()),
            lookback_hours=self._settings.fb_lead_poll_lookback_hours,
            deep_pages=self._settings.fb_lead_poll_deep_pages,
            max_pages=self._settings.fb_lead_poll_max_pages,
        )

        candidates: dict[str, tuple[str, dict[str, Any]]] = {}
        for plan in plans:
            try:
                leads = await poll_form_leads(
                    plan.form_id, plan.since_unix, max_pages=plan.max_pages
                )
            except Exception:  # noqa: BLE001
                # One unreadable form must not sink the sweep for the other 15.
                logger.exception("lead_poll: polling form %s failed", plan.form_id)
                continue
            outcome.forms_polled += 1
            if plan.reason != "routine":
                logger.debug("lead_poll: deep sweep of form %s (%s)", plan.form_id, plan.reason)
            for raw in leads:
                leadgen_id = str(raw.get("id") or "")
                if leadgen_id:
                    candidates[leadgen_id] = (plan.form_id, raw)

        # Which of those do we actually not have? A read, so it happens before we
        # take the lock: on a quiet tick (the normal case) this job then opens no
        # transaction and never interrupts the live resolver at all.
        fresh: list[tuple[str, str, dict[str, Any]]] = []
        if candidates:
            async with async_session_maker() as session:
                known = await self._known(session, list(candidates))
            fresh = [
                (leadgen_id, form_id, raw)
                for leadgen_id, (form_id, raw) in candidates.items()
                if leadgen_id not in known
            ]

        if not fresh and not retry:
            self._log(outcome)
            return outcome

        # Phase 2 — ingest under the resolver's own lock, so a lead can never be
        # POSTed by both paths at once.
        async with async_session_maker() as session:
            if not await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _RESOLVE_LOCK_KEY}
            ):
                logger.info("lead_poll: resolver busy -- deferring to the next tick")
                return outcome

            for leadgen_id, form_id, raw in fresh:
                # Loud on purpose: this is a lead the live path never saw at all.
                logger.warning(
                    "lead_poll: recovering lead %s (form %s) -- no webhook ever arrived",
                    leadgen_id,
                    form_id,
                )
                if await self._resolver.ingest_and_record(
                    session, leadgen_id=leadgen_id, form_id=form_id, raw=raw
                ):
                    outcome.recovered += 1
                else:
                    outcome.failed += 1

            for leadgen_id, form_id in retry:
                # Reuse the polled object when this sweep already fetched it.
                polled = candidates.get(leadgen_id)
                if await self._resolver.ingest_and_record(
                    session,
                    leadgen_id=leadgen_id,
                    form_id=form_id,
                    raw=polled[1] if polled else None,
                ):
                    outcome.retried += 1
                else:
                    outcome.failed += 1

            await session.commit()

        self._log(outcome)
        return outcome

    @staticmethod
    def _log(outcome: PollOutcome) -> None:
        """Always at INFO, even for a clean pass.

        This job is the thing that notices silence, so its own silence must not be
        ambiguous: a heartbeat every 15 min is what tells us the net is still up.
        Quiet passes are the norm, and 96 lines a day is nothing next to the
        resolver's own 2 880.
        """
        logger.info(
            "lead_poll: forms=%d recovered=%d retried=%d failed=%d",
            outcome.forms_polled,
            outcome.recovered,
            outcome.retried,
            outcome.failed,
        )
