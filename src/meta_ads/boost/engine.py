"""IG Auto-Boost — promote fresh IG posts as POST_ENGAGEMENT ads (pipeline A).

Every 6 h the worker walks the linked IG account's recent media and, for each
post it hasn't seen, builds an AdCreative straight from the post ("boost
existing post") plus one PAUSED ad per zone inside two permanent engagement
campaigns (find-or-create by exact name, so re-runs are idempotent):

  B  MB_BOOST_ENG_B_MIX_202607 / RS-BA-ME-XK_BOOST_AUTO   Balkans, no SAC
  A  MB_BOOST_ENG_A_MIX_202607 / DE-AT-CH-PL_BOOST_AUTO   EU, HOUSING SAC + DSA

Money-safety mirrors channels/meta/campaigns.py: ads are born PAUSED and only
flip ACTIVE once Meta's review has passed (effective_status back to plain
PAUSED); the campaign/adset shells stay ACTIVE — with every ad paused they
spend nothing. A per-zone rotation keeps at most MAX_ACTIVE_PER_ZONE boosted
ads (oldest `boosted_at` is paused first, decision → 'rotated_out'). Captions
are compliance-linted (boost/lint.py) before any money is attached.

State lives in `meta.ig_boost_state`, one row per (media, zone); zone='' rows
are media-level terminal decisions (skipped_lint / skipped_type /
skipped_music). decision='error' rows are retried on the next tick — never
within the same tick.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import bindparam, text

from meta_ads.boost.lint import lint_caption
from meta_ads.channels.meta.client import PAGE, SYSTEM_USER, GraphClient, GraphError
from meta_ads.config import get_settings

logger = logging.getLogger(__name__)

MEDIA_FIELDS = "id,media_product_type,media_type,timestamp,caption,permalink"
MEDIA_LIMIT = 25
BOOSTABLE_MEDIA_TYPES = {"VIDEO", "IMAGE", "CAROUSEL_ALBUM"}
DAILY_BUDGET_MINOR = 1200  # €12.00/day per zone, account minor units (cents)
MAX_ACTIVE_PER_ZONE = 6
DSA_TEXT = "5-Star Melia Private Residences Budva"

# Graph throttling codes worth a retry: 17 user request limit, 613 rate
# limit, 80004 ads-management throttling. Everything else fails fast.
_RETRYABLE_CODES = {17, 613, 80004}
_BACKOFF_ATTEMPTS = 3
_BACKOFF_BASE_S = 2.0

_UNLINKED_WARN_EVERY_S = 24 * 3600
_unlinked_warned_at: float = float("-inf")


@dataclass(frozen=True)
class BoostZone:
    code: str  # "B" | "A" — the IGBOOST_<media>_<code> ad-name suffix
    campaign_name: str
    adset_name: str
    countries: tuple[str, ...]
    special_ad_categories: tuple[str, ...] = ()
    sac_countries: tuple[str, ...] = ()
    dsa: str | None = None  # dsa_beneficiary / dsa_payor (EU DSA), if targeting EU


ZONES: tuple[BoostZone, ...] = (
    BoostZone(
        code="B",
        campaign_name="MB_BOOST_ENG_B_MIX_202607",
        adset_name="RS-BA-ME-XK_BOOST_AUTO",
        countries=("RS", "BA", "ME", "XK"),
    ),
    BoostZone(
        code="A",
        campaign_name="MB_BOOST_ENG_A_MIX_202607",
        adset_name="DE-AT-CH-PL_BOOST_AUTO",
        countries=("DE", "AT", "CH", "PL"),
        special_ad_categories=("HOUSING",),
        sac_countries=("DE", "AT", "CH", "PL"),
        dsa=DSA_TEXT,
    ),
)


class GraphLike(Protocol):
    """The slice of GraphClient this engine uses (tests inject a fake)."""

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...

    async def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


def build_boost_creative_fields(*, media_id: str, ig_user_id: str, page_id: str) -> dict[str, str]:
    """AdCreative fields that boost an existing IG post.

    TODO(live-verify): the exact required shape is confirmed on the first live
    run — Meta's "use existing Instagram post" creative is documented as
    {source_instagram_media_id, instagram_user_id}, but some API versions also
    demand the owning Page via `object_story_spec={"page_id": ...}` (error
    ~"requires a page"). If that happens, add
    `"object_story_spec": json.dumps({"page_id": page_id})` here — the page_id
    is already threaded through for exactly that.
    """
    _ = page_id  # kept on the signature for the object_story_spec fallback above
    return {
        "name": f"IGBOOST_CREATIVE_{media_id}",
        "source_instagram_media_id": media_id,
        "instagram_user_id": ig_user_id,
    }


def _is_music_rights_error(err: GraphError) -> bool:
    """Boost refused because the post uses licensed audio / isn't eligible.

    TODO(live-verify): pin the exact error_subcode on the first real hit —
    Meta doesn't document a stable subcode for "licensed music" boosts, so
    until then we classify by message text (per spec: licensed music /
    not eligible → skipped_music).
    """
    e = err.body.get("error", {}) if isinstance(err.body, dict) else {}
    blob = " ".join(
        str(v)
        for v in (e.get("message"), e.get("error_user_title"), e.get("error_user_msg"))
        if v
    ).lower()
    return "licensed music" in blob or "not eligible" in blob


async def _with_backoff(call: Any, *, what: str) -> dict[str, Any]:
    """Run a Graph call, retrying only the known throttling codes."""
    delay = _BACKOFF_BASE_S
    for attempt in range(1, _BACKOFF_ATTEMPTS + 1):
        try:
            return await call()  # type: ignore[no-any-return]
        except GraphError as err:
            e = err.body.get("error", {}) if isinstance(err.body, dict) else {}
            if e.get("code") not in _RETRYABLE_CODES or attempt == _BACKOFF_ATTEMPTS:
                raise
            logger.warning(
                "%s throttled (code=%s) — retry %d/%d in %.0fs",
                what, e.get("code"), attempt, _BACKOFF_ATTEMPTS, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def _warn_unlinked_daily() -> None:
    """Boost is on but no IG account is linked — nag once a day, not per tick."""
    global _unlinked_warned_at
    now = time.monotonic()
    if now - _unlinked_warned_at < _UNLINKED_WARN_EVERY_S:
        return
    _unlinked_warned_at = now
    logger.warning(
        "IG auto-boost is enabled (FB_IG_BOOST_ENABLED=1) but FB_IG_USER_ID is empty — "
        "IG account not linked, ig_boost idles"
    )


@dataclass
class StateRow:
    media_id: str
    zone: str
    decision: str
    ad_id: str | None = None
    creative_id: str | None = None
    boosted_at: datetime | None = None


@dataclass
class BoostOutcome:
    fetched: int = 0
    boosted: int = 0
    skipped_lint: int = 0
    skipped_type: int = 0
    skipped_music: int = 0
    errors: int = 0
    activated: int = 0
    rotated_out: int = 0


class BoostStateStore(Protocol):
    """meta.ig_boost_state accessor contract (tests inject an in-memory fake)."""

    async def rows_for_media(self, media_ids: list[str]) -> dict[str, list[StateRow]]: ...

    async def record(
        self,
        *,
        media_id: str,
        zone: str,
        decision: str,
        lint_hits: str | None = None,
        ad_id: str | None = None,
        creative_id: str | None = None,
        caption_excerpt: str | None = None,
        media_product_type: str | None = None,
        boosted_at: datetime | None = None,
        error: str | None = None,
    ) -> None: ...

    async def boosted_ads(self, zone: str | None = None) -> list[StateRow]: ...

    async def mark_rotated(self, media_id: str, zone: str) -> None: ...


_ROW_COLS = "media_id, zone, decision, ad_id, creative_id, boosted_at"


class IgBoostStore:
    """SQL implementation of BoostStateStore (one short session per op)."""

    async def rows_for_media(self, media_ids: list[str]) -> dict[str, list[StateRow]]:
        if not media_ids:
            return {}
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        stmt = text(
            f"SELECT {_ROW_COLS} FROM meta.ig_boost_state WHERE media_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        out: dict[str, list[StateRow]] = {}
        async with async_session_maker() as s:
            for r in await s.execute(stmt, {"ids": media_ids}):
                out.setdefault(r.media_id, []).append(
                    StateRow(
                        media_id=r.media_id,
                        zone=r.zone,
                        decision=r.decision,
                        ad_id=r.ad_id,
                        creative_id=r.creative_id,
                        boosted_at=r.boosted_at,
                    )
                )
        return out

    async def record(
        self,
        *,
        media_id: str,
        zone: str,
        decision: str,
        lint_hits: str | None = None,
        ad_id: str | None = None,
        creative_id: str | None = None,
        caption_excerpt: str | None = None,
        media_product_type: str | None = None,
        boosted_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        async with async_session_maker() as s:
            await s.execute(
                text(
                    "INSERT INTO meta.ig_boost_state "
                    "(media_id, zone, decision, lint_hits, ad_id, creative_id, "
                    " caption_excerpt, media_product_type, boosted_at, error) "
                    "VALUES (:m, :z, :d, :h, :ad, :cr, :cap, :pt, :b, :e) "
                    "ON CONFLICT (media_id, zone) DO UPDATE SET "
                    "decision=EXCLUDED.decision, lint_hits=EXCLUDED.lint_hits, "
                    "ad_id=EXCLUDED.ad_id, creative_id=EXCLUDED.creative_id, "
                    "caption_excerpt=EXCLUDED.caption_excerpt, "
                    "media_product_type=EXCLUDED.media_product_type, "
                    "boosted_at=EXCLUDED.boosted_at, error=EXCLUDED.error"
                ),
                {
                    "m": media_id, "z": zone, "d": decision, "h": lint_hits,
                    "ad": ad_id, "cr": creative_id, "cap": caption_excerpt,
                    "pt": media_product_type, "b": boosted_at, "e": error,
                },
            )
            await s.commit()

    async def boosted_ads(self, zone: str | None = None) -> list[StateRow]:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        sql = (
            f"SELECT {_ROW_COLS} FROM meta.ig_boost_state "
            "WHERE decision = 'boosted' AND ad_id IS NOT NULL"
        )
        params: dict[str, Any] = {}
        if zone is not None:
            sql += " AND zone = :zone"
            params["zone"] = zone
        sql += " ORDER BY boosted_at ASC"
        async with async_session_maker() as s:
            rows = await s.execute(text(sql), params)
            return [
                StateRow(
                    media_id=r.media_id,
                    zone=r.zone,
                    decision=r.decision,
                    ad_id=r.ad_id,
                    creative_id=r.creative_id,
                    boosted_at=r.boosted_at,
                )
                for r in rows
            ]

    async def mark_rotated(self, media_id: str, zone: str) -> None:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        async with async_session_maker() as s:
            await s.execute(
                text(
                    "UPDATE meta.ig_boost_state SET decision='rotated_out', rotated_at=now() "
                    "WHERE media_id=:m AND zone=:z"
                ),
                {"m": media_id, "z": zone},
            )
            await s.commit()


class IgBoostEngine:
    """One ig_boost tick: discover → lint → boost → activate → rotate."""

    def __init__(
        self,
        *,
        store: BoostStateStore | None = None,
        page_graph: GraphLike | None = None,
        su_graph: GraphLike | None = None,
    ) -> None:
        self._store = store
        self._page_graph = page_graph  # PAGE token — IG media listing
        self._su_graph = su_graph  # System User token — act-level mutations
        self._zone_ids: dict[str, tuple[str, str]] = {}  # code -> (campaign_id, adset_id)

    async def run(self) -> BoostOutcome | None:
        s = get_settings()
        if not s.fb_ig_boost_enabled:
            return None
        if not s.fb_ig_user_id:
            _warn_unlinked_daily()
            return None

        store = self._store if self._store is not None else IgBoostStore()
        async with AsyncExitStack() as stack:
            page_g = self._page_graph or await stack.enter_async_context(
                await GraphClient.for_provider(PAGE)
            )
            su_g = self._su_graph or await stack.enter_async_context(
                await GraphClient.for_provider(SYSTEM_USER)
            )
            outcome = await self._tick(store, page_g, su_g, s)
        logger.info(
            "ig_boost: fetched=%d boosted=%d skipped_lint=%d skipped_type=%d "
            "skipped_music=%d errors=%d activated=%d rotated_out=%d",
            outcome.fetched, outcome.boosted, outcome.skipped_lint, outcome.skipped_type,
            outcome.skipped_music, outcome.errors, outcome.activated, outcome.rotated_out,
        )
        return outcome

    async def _tick(
        self, store: BoostStateStore, page_g: GraphLike, su_g: GraphLike, s: Any
    ) -> BoostOutcome:
        outcome = BoostOutcome()
        media = await self._fetch_media(page_g, s.fb_ig_user_id)
        outcome.fetched = len(media)
        state = await store.rows_for_media([m["id"] for m in media])
        for m in media:
            await self._process_media(store, su_g, s, m, state.get(m["id"], []), outcome)
        await self._activate_reviewed(store, su_g, outcome)
        await self._rotate(store, su_g, outcome)
        return outcome

    async def _fetch_media(self, g: GraphLike, ig_user_id: str) -> list[dict[str, Any]]:
        resp = await _with_backoff(
            lambda: g.get(
                f"{ig_user_id}/media", params={"fields": MEDIA_FIELDS, "limit": MEDIA_LIMIT}
            ),
            what="ig media list",
        )
        return list(resp.get("data") or [])

    # ── per-media decision ────────────────────────────────────────────

    async def _process_media(
        self,
        store: BoostStateStore,
        g: GraphLike,
        s: Any,
        m: dict[str, Any],
        existing: list[StateRow],
        outcome: BoostOutcome,
    ) -> None:
        media_id = m["id"]
        # zone='' rows are media-level terminal skips; zone rows settle their
        # zone unless the last attempt errored ('error' retries next tick).
        if any(r.zone == "" and r.decision != "error" for r in existing):
            return
        settled = {r.zone for r in existing if r.zone and r.decision != "error"}
        todo = [z for z in ZONES if z.code not in settled]
        if not todo:
            return

        caption = m.get("caption") or ""
        product_type = m.get("media_product_type") or ""
        base: dict[str, Any] = {
            "media_id": media_id,
            "caption_excerpt": caption[:200] or None,
            "media_product_type": product_type or None,
        }

        hits = lint_caption(caption)
        if hits:
            logger.warning(
                "ig_boost: media %s caption tripped compliance lint (%s) — not boosting; %s",
                media_id, ", ".join(hits), m.get("permalink") or "",
            )
            await store.record(**base, zone="", decision="skipped_lint", lint_hits=",".join(hits))
            outcome.skipped_lint += 1
            return

        if m.get("media_type") not in BOOSTABLE_MEDIA_TYPES or product_type == "STORY":
            await store.record(**base, zone="", decision="skipped_type")
            outcome.skipped_type += 1
            return

        # One creative per media, shared by both zone ads (reused on retries).
        creative_id = next((r.creative_id for r in existing if r.creative_id), None)
        if creative_id is None:
            try:
                creative_id = await self._create_creative(g, s, media_id)
            except GraphError as err:
                if _is_music_rights_error(err):
                    logger.warning("ig_boost: media %s not boostable (music/rights): %s", media_id, err)
                    await store.record(**base, zone="", decision="skipped_music", error=str(err))
                    outcome.skipped_music += 1
                else:
                    logger.warning("ig_boost: creative for media %s failed: %s", media_id, err)
                    await store.record(**base, zone="", decision="error", error=str(err))
                    outcome.errors += 1
                return

        for zone in todo:
            try:
                _campaign_id, adset_id = await self._ensure_zone(g, s, zone)
                ad_id = await self._create_ad(g, s, zone, adset_id, media_id, creative_id)
                await store.record(
                    **base,
                    zone=zone.code,
                    decision="boosted",
                    ad_id=ad_id,
                    creative_id=creative_id,
                    boosted_at=datetime.now(UTC),
                )
                outcome.boosted += 1
            except GraphError as err:
                # Recorded, tick moves on — the NEXT tick retries this zone.
                if _is_music_rights_error(err):
                    await store.record(
                        **base, zone=zone.code, decision="skipped_music",
                        creative_id=creative_id, error=str(err),
                    )
                    outcome.skipped_music += 1
                else:
                    logger.warning(
                        "ig_boost: boosting media %s in zone %s failed: %s",
                        media_id, zone.code, err,
                    )
                    await store.record(
                        **base, zone=zone.code, decision="error",
                        creative_id=creative_id, error=str(err),
                    )
                    outcome.errors += 1

    # ── Graph plumbing ────────────────────────────────────────────────

    async def _create_creative(self, g: GraphLike, s: Any, media_id: str) -> str:
        fields = build_boost_creative_fields(
            media_id=media_id, ig_user_id=s.fb_ig_user_id, page_id=s.meta_page_id
        )
        resp = await _with_backoff(
            lambda: g.post(f"{s.meta_ad_account_id}/adcreatives", data=fields),
            what="adcreative create",
        )
        return str(resp["id"])

    async def _ensure_zone(self, g: GraphLike, s: Any, zone: BoostZone) -> tuple[str, str]:
        """Find-or-create the permanent zone campaign + adset by exact name."""
        if zone.code in self._zone_ids:
            return self._zone_ids[zone.code]
        act = s.meta_ad_account_id

        campaign_id = await self._find_by_name(g, f"{act}/campaigns", zone.campaign_name)
        if campaign_id is None:
            data: dict[str, Any] = {
                "name": zone.campaign_name,
                "objective": "OUTCOME_ENGAGEMENT",
                # The shell is ACTIVE — delivery is gated per-ad (born PAUSED,
                # flipped ACTIVE only after review); an ACTIVE campaign whose
                # every ad is paused spends nothing.
                "status": "ACTIVE",
                "special_ad_categories": json.dumps(list(zone.special_ad_categories)),
                "is_adset_budget_sharing_enabled": "false",  # ABO, as in campaigns.py
            }
            if zone.sac_countries:
                data["special_ad_category_country"] = json.dumps(list(zone.sac_countries))
            resp = await _with_backoff(
                lambda: g.post(f"{act}/campaigns", data=data), what="campaign create"
            )
            campaign_id = str(resp["id"])

        adset_id = await self._find_by_name(g, f"{campaign_id}/adsets", zone.adset_name)
        if adset_id is None:
            targeting: dict[str, Any] = {
                "geo_locations": {"countries": list(zone.countries)},
                "age_min": 18,
                "age_max": 65,
                # Explicit opt-out — Meta requires a decision (subcode 1870227).
                # TODO(live-verify): HOUSING-SAC ad sets may reject
                # targeting_automation outright; drop it for zone A if the
                # first live run errors on this field.
                "targeting_automation": {"advantage_audience": 0},
            }
            adset_data: dict[str, Any] = {
                "name": zone.adset_name,
                "campaign_id": campaign_id,
                "optimization_goal": "POST_ENGAGEMENT",
                "billing_event": "IMPRESSIONS",
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "daily_budget": str(DAILY_BUDGET_MINOR),
                "targeting": json.dumps(targeting),
                "status": "ACTIVE",
            }
            if zone.dsa:
                adset_data["dsa_beneficiary"] = zone.dsa
                adset_data["dsa_payor"] = zone.dsa
            resp = await _with_backoff(
                lambda: g.post(f"{act}/adsets", data=adset_data), what="adset create"
            )
            adset_id = str(resp["id"])

        self._zone_ids[zone.code] = (campaign_id, adset_id)
        return campaign_id, adset_id

    async def _find_by_name(self, g: GraphLike, edge: str, name: str) -> str | None:
        params = {
            "fields": "id,name",
            "filtering": json.dumps([{"field": "name", "operator": "EQUAL", "value": name}]),
            "limit": 25,
        }
        resp = await _with_backoff(lambda: g.get(edge, params=params), what=f"find {name!r}")
        for row in resp.get("data") or []:
            if row.get("name") == name:
                return str(row["id"])
        return None

    async def _create_ad(
        self, g: GraphLike, s: Any, zone: BoostZone, adset_id: str, media_id: str, creative_id: str
    ) -> str:
        data = {
            "name": f"IGBOOST_{media_id}_{zone.code}",
            "adset_id": adset_id,
            "creative": json.dumps({"creative_id": creative_id}),
            "status": "PAUSED",  # born paused; activated only after review passes
        }
        resp = await _with_backoff(
            lambda: g.post(f"{s.meta_ad_account_id}/ads", data=data), what="ad create"
        )
        return str(resp["id"])

    async def _post_status(self, g: GraphLike, object_id: str, status: str) -> None:
        await _with_backoff(
            lambda: g.post(object_id, data={"status": status}), what=f"status={status}"
        )

    async def _effective_statuses(self, g: GraphLike, ad_ids: list[str]) -> dict[str, str]:
        """Batch-read effective_status via GET /?ids=... (50 per call)."""
        out: dict[str, str] = {}
        for i in range(0, len(ad_ids), 50):
            chunk = ad_ids[i : i + 50]
            params = {"ids": ",".join(chunk), "fields": "effective_status"}
            resp = await _with_backoff(
                lambda p=params: g.get("", params=p), what="effective_status read"
            )
            for ad_id, obj in resp.items():
                if isinstance(obj, dict) and obj.get("effective_status"):
                    out[ad_id] = obj["effective_status"]
        return out

    # ── post-review activation + rotation ─────────────────────────────

    async def _activate_reviewed(
        self, store: BoostStateStore, g: GraphLike, outcome: BoostOutcome
    ) -> None:
        """Flip review-passed ads live: our ads are configured PAUSED, so an
        effective_status of plain PAUSED (not PENDING_REVIEW / DISAPPROVED /
        WITH_ISSUES) means review is done and the pause is the only gate left.

        TODO(live-verify): confirm on the first live batch that in-review ads
        really report PENDING_REVIEW here; if Meta reports paused-while-in-
        review ads as PAUSED too, switch this check to ad_review_feedback.
        Only decision='boosted' rows are considered — 'rotated_out' ads are
        paused on purpose and must never be re-activated.
        """
        rows = await store.boosted_ads()
        if not rows:
            return
        statuses = await self._effective_statuses(g, [r.ad_id for r in rows if r.ad_id])
        for r in rows:
            if r.ad_id is None or statuses.get(r.ad_id) != "PAUSED":
                continue
            await self._post_status(g, r.ad_id, "ACTIVE")
            logger.info("ig_boost: ad %s (media %s, zone %s) passed review — ACTIVE", r.ad_id, r.media_id, r.zone)
            outcome.activated += 1

    async def _rotate(self, store: BoostStateStore, g: GraphLike, outcome: BoostOutcome) -> None:
        """Keep ≤ MAX_ACTIVE_PER_ZONE boosted ads per zone; pause the oldest."""
        for zone in ZONES:
            rows = await store.boosted_ads(zone=zone.code)  # boosted_at ASC
            excess = len(rows) - MAX_ACTIVE_PER_ZONE
            if excess <= 0:
                continue
            for r in rows[:excess]:
                if r.ad_id is None:
                    continue
                await self._post_status(g, r.ad_id, "PAUSED")
                await store.mark_rotated(r.media_id, r.zone)
                logger.info(
                    "ig_boost: rotated out ad %s (media %s, zone %s, boosted %s)",
                    r.ad_id, r.media_id, r.zone, r.boosted_at,
                )
                outcome.rotated_out += 1
