"""ig_boost job logic — fake Graph client + in-memory state store (no network, no DB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

import meta_ads.boost.engine as engine_mod
from meta_ads.boost.engine import (
    MAX_ACTIVE_PER_ZONE,
    BoostOutcome,
    IgBoostEngine,
    StateRow,
    _with_backoff,
)
from meta_ads.channels.meta.client import GraphError

IG_USER = "17890000000000000"


def fake_settings(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "fb_ig_boost_enabled": True,
        "fb_ig_boost_lint_enabled": False,  # D-11: default no filters
        "fb_ig_user_id": IG_USER,
        "meta_ad_account_id": "act_1",
        "meta_page_id": "page_1",
    }
    base.update(over)
    return SimpleNamespace(**base)


def media_item(mid: str = "m1", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": mid,
        "media_type": "IMAGE",
        "media_product_type": "FEED",
        "caption": "Sunset over the Budva riviera",
        "timestamp": "2026-07-10T08:00:00+0000",
        "permalink": f"https://www.instagram.com/p/{mid}/",
    }
    base.update(over)
    return base


class FakeStore:
    """In-memory stand-in for IgBoostStore (same duck-typed contract)."""

    def __init__(self, rows: list[StateRow] | None = None) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        for r in rows or []:
            self.rows[(r.media_id, r.zone)] = {
                "media_id": r.media_id,
                "zone": r.zone,
                "decision": r.decision,
                "ad_id": r.ad_id,
                "creative_id": r.creative_id,
                "boosted_at": r.boosted_at,
            }

    @staticmethod
    def _to_state_row(row: dict[str, Any]) -> StateRow:
        return StateRow(
            media_id=row["media_id"],
            zone=row["zone"],
            decision=row["decision"],
            ad_id=row.get("ad_id"),
            creative_id=row.get("creative_id"),
            boosted_at=row.get("boosted_at"),
        )

    async def rows_for_media(self, media_ids: list[str]) -> dict[str, list[StateRow]]:
        out: dict[str, list[StateRow]] = {}
        for (mid, _zone), row in self.rows.items():
            if mid in media_ids:
                out.setdefault(mid, []).append(self._to_state_row(row))
        return out

    async def record(self, *, media_id: str, zone: str, decision: str, **fields: Any) -> None:
        self.rows[(media_id, zone)] = {"media_id": media_id, "zone": zone, "decision": decision, **fields}

    async def boosted_ads(self, zone: str | None = None) -> list[StateRow]:
        rows = [
            r
            for r in self.rows.values()
            if r["decision"] == "boosted" and r.get("ad_id") and (zone is None or r["zone"] == zone)
        ]
        rows.sort(key=lambda r: r["boosted_at"])
        return [self._to_state_row(r) for r in rows]

    async def mark_rotated(self, media_id: str, zone: str) -> None:
        row = self.rows[(media_id, zone)]
        row["decision"] = "rotated_out"
        row["rotated_at"] = datetime.now(UTC)


class FakeGraph:
    """Duck-typed GraphClient: canned GETs, scripted POST errors, id counters."""

    def __init__(
        self,
        *,
        media: list[dict[str, Any]] | None = None,
        campaigns: list[dict[str, str]] | None = None,
        adsets: list[dict[str, str]] | None = None,
        effective: dict[str, str] | None = None,
        post_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.media = media or []
        self.campaigns = campaigns or []  # existing [{"id","name"}]
        self.adsets = adsets or []  # existing [{"id","name"}]
        self.effective = effective or {}  # ad_id -> effective_status (default PENDING_REVIEW)
        self.post_errors = post_errors or {}  # path suffix -> exception to raise
        self.gets: list[tuple[str, dict[str, Any]]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self._seq = 0

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq}"

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.gets.append((path, params or {}))
        if path.endswith("/media"):
            return {"data": self.media}
        if path.endswith("/campaigns"):
            return {"data": self.campaigns}
        if path.endswith("/adsets"):
            return {"data": self.adsets}
        if path == "":  # batch ?ids= effective_status read
            ids = (params or {}).get("ids", "")
            return {
                i: {"id": i, "effective_status": self.effective.get(i, "PENDING_REVIEW")}
                for i in ids.split(",")
                if i
            }
        raise AssertionError(f"unexpected GET {path}")

    async def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.posts.append((path, data or {}))
        for suffix, err in self.post_errors.items():
            if path.endswith(suffix):
                raise err
        if path.endswith("/campaigns"):
            row = {"id": self._next("cmp"), "name": (data or {}).get("name", "")}
            self.campaigns.append(row)
            return {"id": row["id"]}
        if path.endswith("/adsets"):
            row = {"id": self._next("as"), "name": (data or {}).get("name", "")}
            self.adsets.append(row)
            return {"id": row["id"]}
        if path.endswith("/adcreatives"):
            return {"id": self._next("cr")}
        if path.endswith("/ads"):
            return {"id": self._next("ad")}
        return {"success": True}  # POST /<object_id> status flips


def make_engine(g: FakeGraph, store: FakeStore) -> IgBoostEngine:
    return IgBoostEngine(store=store, page_graph=g, su_graph=g)


def ad_creates(g: FakeGraph) -> list[dict[str, Any]]:
    return [d for p, d in g.posts if p.endswith("/ads")]


def status_flips(g: FakeGraph) -> list[tuple[str, str]]:
    return [(p, d["status"]) for p, d in g.posts if set(d) == {"status"}]


# ── gates ─────────────────────────────────────────────────────────────


async def test_disabled_is_a_silent_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings(fb_ig_boost_enabled=False))
    g, store = FakeGraph(media=[media_item()]), FakeStore()
    assert await make_engine(g, store).run() is None
    assert g.gets == [] and g.posts == []
    assert store.rows == {}


async def test_unlinked_ig_warns_once_daily_and_exits(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings(fb_ig_user_id=""))
    monkeypatch.setattr(engine_mod, "_unlinked_warned_at", float("-inf"))
    g, store = FakeGraph(media=[media_item()]), FakeStore()
    with caplog.at_level("WARNING", logger="meta_ads.boost.engine"):
        assert await make_engine(g, store).run() is None
        assert await make_engine(g, store).run() is None  # second tick inside 24 h
    assert g.gets == [] and g.posts == []
    warned = [r for r in caplog.records if "FB_IG_USER_ID" in r.message]
    assert len(warned) == 1  # daily throttle: one warning, not one per tick


# ── boosting a new post ───────────────────────────────────────────────


async def test_new_post_gets_paused_ads_in_both_zones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    g, store = FakeGraph(media=[media_item("m1")]), FakeStore()
    out = await make_engine(g, store).run()
    assert isinstance(out, BoostOutcome)

    # one creative from the existing IG post, shared by both zone ads
    creatives = [d for p, d in g.posts if p.endswith("/adcreatives")]
    assert len(creatives) == 1
    assert creatives[0]["source_instagram_media_id"] == "m1"
    assert creatives[0]["instagram_user_id"] == IG_USER

    ads = ad_creates(g)
    assert {d["name"] for d in ads} == {"IGBOOST_m1_B", "IGBOOST_m1_A"}
    assert all(d["status"] == "PAUSED" for d in ads)

    # permanent campaigns + adsets created with the zone parameters
    campaigns = {d["name"]: d for p, d in g.posts if p.endswith("/campaigns")}
    assert set(campaigns) == {"MB_BOOST_ENG_B_MIX_202607", "MB_BOOST_ENG_A_MIX_202607"}
    assert campaigns["MB_BOOST_ENG_B_MIX_202607"]["special_ad_categories"] == "[]"
    assert campaigns["MB_BOOST_ENG_A_MIX_202607"]["special_ad_categories"] == '["HOUSING"]'
    assert campaigns["MB_BOOST_ENG_A_MIX_202607"]["special_ad_category_country"] == '["DE", "AT", "CH", "PL"]'
    assert all(d["objective"] == "OUTCOME_ENGAGEMENT" for d in campaigns.values())

    adsets = {d["name"]: d for p, d in g.posts if p.endswith("/adsets")}
    assert set(adsets) == {"RS-BA-ME-XK_BOOST_AUTO", "DE-AT-CH-PL_BOOST_AUTO"}
    for d in adsets.values():
        assert d["optimization_goal"] == "POST_ENGAGEMENT"
        assert d["billing_event"] == "IMPRESSIONS"
        assert d["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
        assert d["daily_budget"] == "1200"
    assert adsets["DE-AT-CH-PL_BOOST_AUTO"]["dsa_beneficiary"] == engine_mod.DSA_TEXT
    assert adsets["DE-AT-CH-PL_BOOST_AUTO"]["dsa_payor"] == engine_mod.DSA_TEXT
    assert "dsa_beneficiary" not in adsets["RS-BA-ME-XK_BOOST_AUTO"]

    # state: one 'boosted' row per zone, sharing the creative
    assert store.rows[("m1", "B")]["decision"] == "boosted"
    assert store.rows[("m1", "A")]["decision"] == "boosted"
    assert store.rows[("m1", "B")]["ad_id"] and store.rows[("m1", "A")]["ad_id"]
    assert store.rows[("m1", "B")]["creative_id"] == store.rows[("m1", "A")]["creative_id"]
    assert out.boosted == 2 and out.activated == 0  # fresh ads are PENDING_REVIEW → stay paused
    assert status_flips(g) == []


async def test_existing_campaigns_are_reused_not_recreated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    g = FakeGraph(
        media=[media_item("m1")],
        campaigns=[
            {"id": "cmpB", "name": "MB_BOOST_ENG_B_MIX_202607"},
            {"id": "cmpA", "name": "MB_BOOST_ENG_A_MIX_202607"},
        ],
        adsets=[
            {"id": "asB", "name": "RS-BA-ME-XK_BOOST_AUTO"},
            {"id": "asA", "name": "DE-AT-CH-PL_BOOST_AUTO"},
        ],
    )
    store = FakeStore()
    out = await make_engine(g, store).run()
    assert not [p for p, _ in g.posts if p.endswith(("/campaigns", "/adsets"))]
    assert {d["adset_id"] for d in ad_creates(g)} == {"asB", "asA"}
    assert out is not None and out.boosted == 2


async def test_seen_media_is_not_reprocessed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    t = datetime.now(UTC)
    store = FakeStore(
        [
            StateRow("m1", "B", "boosted", ad_id="adB", creative_id="cr1", boosted_at=t),
            StateRow("m1", "A", "boosted", ad_id="adA", creative_id="cr1", boosted_at=t),
        ]
    )
    g = FakeGraph(media=[media_item("m1")])
    out = await make_engine(g, store).run()
    assert ad_creates(g) == []
    assert not [p for p, _ in g.posts if p.endswith("/adcreatives")]
    assert out is not None and out.boosted == 0


# ── skips ─────────────────────────────────────────────────────────────


async def test_banned_caption_boosts_when_lint_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-11 default: никаких фильтров — даже 'гарантированная доходность' бустится."""
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    g = FakeGraph(media=[media_item("m2", caption="Гарантированная доходность 8%!")])
    store = FakeStore()
    out = await make_engine(g, store).run()
    assert out is not None and out.skipped_lint == 0
    assert out.boosted == 2  # обе зоны


async def test_banned_caption_is_skipped_lint_no_ad(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        engine_mod, "get_settings", lambda: fake_settings(fb_ig_boost_lint_enabled=True)
    )
    g = FakeGraph(media=[media_item("m2", caption="Гарантированная доходность 8%!")])
    store = FakeStore()
    with caplog.at_level("WARNING", logger="meta_ads.boost.engine"):
        out = await make_engine(g, store).run()
    row = store.rows[("m2", "")]
    assert row["decision"] == "skipped_lint"
    assert "guarantee:" in row["lint_hits"] and "yield_roi:" in row["lint_hits"]
    assert g.posts == []  # no creative, no campaign, no ad — no money near this caption
    assert out is not None and out.skipped_lint == 1
    assert any("compliance lint" in r.message for r in caplog.records)


async def test_stories_and_unsupported_types_are_skipped_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    g = FakeGraph(
        media=[
            media_item("m3", media_type="VIDEO", media_product_type="STORY"),
            media_item("m4", media_type="AUDIO"),
        ]
    )
    store = FakeStore()
    out = await make_engine(g, store).run()
    assert store.rows[("m3", "")]["decision"] == "skipped_type"
    assert store.rows[("m4", "")]["decision"] == "skipped_type"
    assert g.posts == []
    assert out is not None and out.skipped_type == 2


async def test_licensed_music_error_becomes_skipped_music(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    err = GraphError(
        400,
        {"error": {"code": 10, "error_subcode": 1885183,
                   "message": "This post can't be boosted because it contains licensed music"}},
    )
    g = FakeGraph(
        media=[media_item("m5", media_type="VIDEO", media_product_type="REELS")],
        post_errors={"/adcreatives": err},
    )
    store = FakeStore()
    out = await make_engine(g, store).run()
    row = store.rows[("m5", "")]
    assert row["decision"] == "skipped_music"
    assert "licensed music" in row["error"]
    assert ad_creates(g) == []
    assert out is not None and out.skipped_music == 1


# ── errors + next-tick retry ──────────────────────────────────────────


async def test_other_error_is_recorded_and_not_retried_within_the_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    err = GraphError(500, {"error": {"code": 1, "message": "An unknown error occurred"}})
    g = FakeGraph(media=[media_item("m6")], post_errors={"/ads": err})
    store = FakeStore()
    out = await make_engine(g, store).run()
    assert store.rows[("m6", "B")]["decision"] == "error"
    assert store.rows[("m6", "A")]["decision"] == "error"
    assert "unknown error" in store.rows[("m6", "B")]["error"]
    assert len(ad_creates(g)) == 2  # exactly one attempt per zone, no same-tick retry
    assert out is not None and out.errors == 2


async def test_error_rows_are_retried_next_tick_reusing_the_creative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    store = FakeStore(
        [
            StateRow("m6", "B", "error", creative_id="cr1"),
            StateRow("m6", "A", "error", creative_id="cr1"),
        ]
    )
    g = FakeGraph(media=[media_item("m6")])
    out = await make_engine(g, store).run()
    assert not [p for p, _ in g.posts if p.endswith("/adcreatives")]  # cr1 reused
    assert len(ad_creates(g)) == 2
    assert store.rows[("m6", "B")]["decision"] == "boosted"
    assert store.rows[("m6", "B")]["creative_id"] == "cr1"
    assert out is not None and out.boosted == 2


# ── activation after review ───────────────────────────────────────────


async def test_review_passed_ads_activate_but_rotated_and_inreview_do_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    t = datetime.now(UTC)
    store = FakeStore(
        [
            StateRow("mA", "B", "boosted", ad_id="ad_ok", creative_id="c", boosted_at=t),
            StateRow("mB", "B", "boosted", ad_id="ad_review", creative_id="c", boosted_at=t),
            StateRow("mC", "B", "rotated_out", ad_id="ad_rot", creative_id="c", boosted_at=t),
        ]
    )
    g = FakeGraph(
        media=[],
        effective={"ad_ok": "PAUSED", "ad_review": "PENDING_REVIEW", "ad_rot": "PAUSED"},
    )
    out = await make_engine(g, store).run()
    assert status_flips(g) == [("ad_ok", "ACTIVE")]  # rotated_out never re-activates
    assert out is not None and out.activated == 1


# ── rotation ──────────────────────────────────────────────────────────


async def test_seventh_boost_rotates_out_the_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_mod, "get_settings", lambda: fake_settings())
    t0 = datetime(2026, 7, 1, tzinfo=UTC)
    rows = [
        StateRow(f"mm{i}", "B", "boosted", ad_id=f"ad{i}", creative_id=f"cr{i}",
                 boosted_at=t0 + timedelta(hours=i))
        for i in range(MAX_ACTIVE_PER_ZONE + 1)  # 7 boosted in zone B
    ]
    store = FakeStore(rows)
    g = FakeGraph(media=[], effective={f"ad{i}": "ACTIVE" for i in range(7)})
    out = await make_engine(g, store).run()
    assert ("ad0", "PAUSED") in status_flips(g)  # oldest boosted_at paused
    assert store.rows[("mm0", "B")]["decision"] == "rotated_out"
    assert store.rows[("mm0", "B")]["rotated_at"] is not None
    assert all(store.rows[(f"mm{i}", "B")]["decision"] == "boosted" for i in range(1, 7))
    assert out is not None and out.rotated_out == 1


# ── backoff helper ────────────────────────────────────────────────────


async def test_backoff_retries_throttling_codes_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def no_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr(engine_mod.asyncio, "sleep", no_sleep)

    calls = {"n": 0}

    async def flaky() -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise GraphError(400, {"error": {"code": 613, "message": "rate limit"}})
        return {"id": "ok"}

    assert (await _with_backoff(flaky, what="test"))["id"] == "ok"
    assert calls["n"] == 3 and sleeps == [2.0, 4.0]

    async def fatal() -> dict[str, Any]:
        raise GraphError(400, {"error": {"code": 100, "message": "bad param"}})

    with pytest.raises(GraphError):
        await _with_backoff(fatal, what="test")
