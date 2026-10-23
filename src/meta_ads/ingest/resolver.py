"""Pipeline B — resolve queued leadgen_ids and hand them to the CRM.

The CRM relay route inserts `leadgen_id` into public.meta_inbound_leadgen and
NOTIFYs 'meta_leadgen'. We read that queue via `ads_contract.v_meta_inbound`,
resolve the full lead over Graph (Page token), and POST it (HMAC-signed) to the
CRM ingest route — the CRM stays the sole writer of public.leads.

Idempotency: `meta.processed_inbound` keyed on leadgen_id (webhook + polling
both funnel here).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from meta_ads.channels.meta.client import GraphError
from meta_ads.channels.meta.leads import (
    field_data_to_map,
    resolve_ad_names,
    resolve_form_name,
    resolve_lead,
)
from meta_ads.config import get_settings
from meta_ads.ingest.contract import CrmResult, connection_key, parse_crm_result
from meta_ads.ingest.form_answers import FormQuestionsCache, build_answers
from meta_ads.security import sign_ingest

logger = logging.getLogger(__name__)

# In-process caches — ads/forms repeat across leads, names rarely change, and
# the worker restarts on every deploy.
_ad_names_cache: dict[str, dict[str, str]] = {}
_form_name_cache: dict[str, str] = {}
# Question definitions (the labels behind a lead's answers) — memo on top of
# meta.leadgen_form_questions, see meta_ads.ingest.form_answers.
_form_questions = FormQuestionsCache()

# Single-flight key for the resolver (arbitrary, stable): "metald" in hex.
_RESOLVE_LOCK_KEY = 0x6D6574616C64


async def _names_for(
    ad_id: str | None, form_id: str | None, page_id: str | None = None
) -> dict[str, str]:
    """Best-effort display names for the lead's attribution (never fatal)."""
    out: dict[str, str] = {}
    if ad_id:
        try:
            if ad_id not in _ad_names_cache:
                _ad_names_cache[ad_id] = await resolve_ad_names(ad_id)
            out.update(_ad_names_cache[ad_id])
        except Exception:  # noqa: BLE001
            logger.warning("could not resolve ad names for %s", ad_id)
    if form_id:
        try:
            if form_id not in _form_name_cache:
                _form_name_cache[form_id] = await resolve_form_name(form_id, page_id)
            if _form_name_cache[form_id]:
                out["form_name"] = _form_name_cache[form_id]
        except Exception:  # noqa: BLE001
            logger.warning("could not resolve form name for %s", form_id)
    return out


async def build_crm_payload(
    leadgen_id: str,
    raw: dict[str, Any],
    form_id_hint: str | None = None,
    page_id: str | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Graph lead object -> the CRM ingest contract.

    The single place the payload is shaped: the live resolver and the lead_poll
    reconciler both go through here, so a recovered lead is byte-identical to a
    webhook-delivered one.

    `fields` is the flat field_data map the CRM reads identity from; `answers`
    is the same data for everything that is NOT identity, labeled against the
    form's questions (meta_ads.ingest.form_answers) so the CRM can show the
    manager what the visitor picked rather than `budget_2`. `session` lets the
    label cache read/write meta.leadgen_form_questions; without it (tests,
    ad-hoc calls) labels come from the memo or a direct Graph read.
    """
    settings = get_settings()
    page_id = page_id or settings.meta_page_id
    if raw.get("id") is not None and str(raw["id"]) != leadgen_id:
        raise ValueError("Resolved lead identity differs from the queued lead")
    if form_id_hint and raw.get("form_id") and str(raw["form_id"]) != form_id_hint:
        raise ValueError("Resolved form identity differs from the queued form")
    form_id = raw.get("form_id") or form_id_hint
    names = await _names_for(raw.get("ad_id"), form_id, page_id)
    fields = field_data_to_map(raw.get("field_data", []))
    payload: dict[str, Any] = {
        "contract_version": 2,
        "connection_key": connection_key(settings.meta_app_id, page_id),
        "page_id": page_id,
        "leadgen_id": leadgen_id,
        "form_id": form_id,
        "created_time": raw.get("created_time"),
        "campaign_id": raw.get("campaign_id"),
        "adset_id": raw.get("adset_id"),
        "ad_id": raw.get("ad_id"),
        "platform": raw.get("platform"),
        "is_organic": raw.get("is_organic"),
        **names,  # campaign_name / adset_name / ad_name / form_name
        "fields": fields,
    }
    questions = await _form_questions.get(session, form_id, page_id) if form_id else None
    answers = build_answers(fields, questions)
    if answers:
        payload["answers"] = answers
    return payload


@dataclass
class ResolveOutcome:
    fetched: int = 0
    ingested: int = 0
    failed: int = 0


@dataclass
class _Inbound:
    id: int
    leadgen_id: str
    form_id: str | None
    # Page the webhook relay recorded — the lead is only readable with THAT
    # page's token (multi-page). None (pre-multi-page rows) = the primary Page.
    page_id: str | None = None


class InboundResolver:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def _fetch_unprocessed(self, session: AsyncSession, limit: int) -> list[_Inbound]:
        rows = await session.execute(
            text(
                "SELECT i.id, i.leadgen_id, i.form_id, i.page_id "
                "FROM ads_contract.v_meta_inbound i "
                "LEFT JOIN meta.processed_inbound p ON p.leadgen_id = i.leadgen_id "
                "WHERE p.leadgen_id IS NULL "
                "ORDER BY i.id ASC LIMIT :lim"
            ),
            {"lim": limit},
        )
        return [
            _Inbound(id=r.id, leadgen_id=r.leadgen_id, form_id=r.form_id, page_id=r.page_id)
            for r in rows
        ]

    async def _record(
        self, session: AsyncSession, item: _Inbound, *, result: CrmResult | None, error: str | None
    ) -> None:
        # Keep the FIRST durable receipt intact, including an agency inquiry with
        # no matched client. A late error or racing response cannot change its kind.
        accepted = "(meta.processed_inbound.crm_lead_id IS NOT NULL OR meta.processed_inbound.agency_inquiry_id IS NOT NULL)"
        result_columns = ["result_kind", "crm_lead_id", "agency_inquiry_id", "agency_lead_id", "match_status"]
        keep_receipt = ", ".join(
            f"{column} = CASE WHEN {accepted} THEN meta.processed_inbound.{column} ELSE EXCLUDED.{column} END"
            for column in result_columns
        )
        await session.execute(
            text(
                "INSERT INTO meta.processed_inbound "
                "(leadgen_id, form_id, page_id, connection_key, result_kind, crm_lead_id, "
                "agency_inquiry_id, agency_lead_id, match_status, delivered_at, error, attempts, processed_at) "
                "VALUES (:lid, :fid, :pid, :connection, :kind, :clid, :inquiry, :agency_lead, :match, CASE WHEN CAST(:kind AS varchar) IS NOT NULL THEN clock_timestamp() ELSE NULL END, :err, 1, clock_timestamp()) "
                "ON CONFLICT (leadgen_id) DO UPDATE SET " + keep_receipt + ", "
                "delivered_at = COALESCE(meta.processed_inbound.delivered_at, EXCLUDED.delivered_at), "
                "page_id = COALESCE(meta.processed_inbound.page_id, EXCLUDED.page_id), "
                "connection_key = COALESCE(meta.processed_inbound.connection_key, EXCLUDED.connection_key), "
                f"error = CASE WHEN {accepted} OR EXCLUDED.crm_lead_id IS NOT NULL "
                "OR EXCLUDED.agency_inquiry_id IS NOT NULL THEN NULL ELSE EXCLUDED.error END, "
                "attempts = meta.processed_inbound.attempts + 1, processed_at = clock_timestamp()"
            ),
            {
                "lid": item.leadgen_id, "fid": item.form_id, "pid": item.page_id,
                "connection": (connection_key(self._settings.meta_app_id, item.page_id or self._settings.meta_page_id)
                               if self._settings.meta_app_id and (item.page_id or self._settings.meta_page_id) else None),
                "kind": result.kind if result else None,
                "clid": result.crm_lead_id if result else None,
                "inquiry": result.agency_inquiry_id if result else None,
                "agency_lead": result.agency_lead_id if result else None,
                "match": result.match_status if result else None,
                "err": error,
            },
        )

    async def _post_to_crm(self, lead: dict[str, Any]) -> CrmResult:
        """HMAC-sign and require a validated durable receipt from the CRM."""
        body = json.dumps(lead, separators=(",", ":")).encode()
        headers = {"content-type": "application/json", "x-fb-signature": sign_ingest(body)}
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(self._settings.crm_ingest_url, content=body, headers=headers)
            resp.raise_for_status()
            return parse_crm_result(resp.json() if resp.content else {})

    async def ingest_and_record(
        self,
        session: AsyncSession,
        *,
        leadgen_id: str,
        form_id: str | None,
        raw: dict[str, Any] | None = None,
        page_id: str | None = None,
    ) -> bool:
        """Resolve -> POST to the CRM -> record the outcome. Never raises.

        `raw` lets a caller hand over a lead object it already holds: poll_form_leads
        returns the same shape as resolve_lead, so reconciling costs no second Graph
        call per lead. `page_id` picks the owning Page's token for the Graph reads
        (multi-page); None = the primary Page. Returns True when the CRM took the
        lead.
        """
        item = _Inbound(id=0, leadgen_id=leadgen_id, form_id=form_id, page_id=page_id or self._settings.meta_page_id)
        # The poller's candidate list was read before acquiring the shared lock.
        # Recheck here so a concurrently accepted event is never posted again.
        if await session.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM meta.processed_inbound WHERE leadgen_id = :id "
            "AND (crm_lead_id IS NOT NULL OR agency_inquiry_id IS NOT NULL))"
        ), {"id": leadgen_id}):
            return True
        try:
            lead = raw if raw is not None else await resolve_lead(leadgen_id, page_id)
            payload = await build_crm_payload(leadgen_id, lead, form_id, page_id, session=session)
            result = await self._post_to_crm(payload)
            await self._record(session, item, result=result, error=None)
            return True
        except Exception as exc:  # noqa: BLE001
            # Graph error strings can include contact data or token-bearing URLs.
            # Persist and log only stable categories and numeric provider codes.
            if isinstance(exc, GraphError):
                code = exc.body.get("error", {}).get("code")
                error = f"provider_http_{exc.status}_code_{code if isinstance(code, int) else 'unknown'}"
            elif isinstance(exc, httpx.HTTPStatusError):
                error = f"crm_http_{exc.response.status_code}"
                try:
                    response = exc.response.json()
                    category = response.get("error") if isinstance(response, dict) else None
                    if category in {"meta_source_unmapped", "meta_source_disabled", "meta_contract_upgrade_required", "agency_intake_unavailable", "invalid_agency_intake"}:
                        error = f"crm_{category}"
                except (ValueError, TypeError):
                    pass
            elif isinstance(exc, httpx.TimeoutException):
                error = "delivery_timeout"
            elif isinstance(exc, httpx.RequestError):
                error = "delivery_unavailable"
            elif isinstance(exc, ValueError):
                error = "invalid_delivery_contract"
            else:
                error = "delivery_failed"
            logger.warning("resolve failed for leadgen_id=%s: %s", leadgen_id, error)
            await self._record(session, item, result=None, error=error)
            return False

    async def run(self, *, limit: int = 100) -> ResolveOutcome:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        outcome = ResolveOutcome()
        async with async_session_maker() as session:
            # Single-flight. This job fires from BOTH the 30 s timer and the LISTEN
            # callback -- separate asyncio tasks, so APScheduler's max_instances=1 does
            # not cover them -- and _fetch_unprocessed cannot see rows the other run has
            # resolved but not yet committed. Without the lock both runs resolve the same
            # leadgen_id and POST it twice, the loser tripping the CRM's unique
            # external-key index with a 500 (15% of rows show attempts > 1). The lock is
            # transaction-scoped: it releases on commit/rollback as this session closes.
            # A skipped tick costs at most 30 s, and the next tick picks the work up.
            if not await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _RESOLVE_LOCK_KEY}
            ):
                logger.debug("inbound resolve: another run holds the lock -- skipping")
                return outcome
            items = await self._fetch_unprocessed(session, limit)
            outcome.fetched = len(items)
            for item in items:
                if await self.ingest_and_record(
                    session,
                    leadgen_id=item.leadgen_id,
                    form_id=item.form_id,
                    page_id=item.page_id,
                ):
                    outcome.ingested += 1
                else:
                    outcome.failed += 1
            await session.commit()
        logger.info(
            "inbound resolve: fetched=%d ingested=%d failed=%d",
            outcome.fetched, outcome.ingested, outcome.failed,
        )
        return outcome
