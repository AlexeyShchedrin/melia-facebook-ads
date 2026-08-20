"""lead_poll reconciler — pure planning logic + the run loop against fakes (no network, no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import meta_ads.ingest.poller as poller_mod
from meta_ads.ingest.poller import LeadPoller, plan_polls

NOW = 1_760_000_000  # fixed clock; the real job passes datetime.now(UTC)
DAY = 86_400


def form(fid: str, *, leads: int | None = 0, status: str | None = "ACTIVE") -> dict[str, Any]:
    return {"id": fid, "status": status, "leads_count": leads, "name": f"LF_{fid}"}


def fake_settings(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "fb_lead_poll_enabled": True,
        "fb_lead_poll_lookback_hours": 24,
        "fb_lead_poll_deep_pages": 2,
        "fb_lead_poll_max_pages": 5,
        "fb_lead_poll_max_attempts": 5,
        "fb_lead_poll_retry_limit": 25,
    }
    base.update(over)
    return SimpleNamespace(**base)


def planned(forms: list[dict[str, Any]], counts: dict[str, int]) -> list[Any]:
    return plan_polls(
        forms, counts, now_unix=NOW, lookback_hours=24, deep_pages=2, max_pages=5
    )


# ── planning ────────────────────────────────────────────────────────────────


def test_form_that_never_took_a_lead_is_skipped() -> None:
    assert planned([form("f1", leads=0)], {}) == []


def test_inactive_form_is_skipped() -> None:
    assert planned([form("f1", leads=90, status="ARCHIVED")], {"f1": 10}) == []


def test_routine_window_uses_the_lookback_cutoff() -> None:
    [plan] = planned([form("f1", leads=10)], {"f1": 10})
    assert plan.since_unix == NOW - DAY
    assert plan.max_pages == 5
    assert plan.reason == "routine"


def test_meta_counting_more_than_us_triggers_a_deep_sweep() -> None:
    """The one direction leads_count is trustworthy in: they have leads we do not."""
    [plan] = planned([form("f1", leads=833)], {"f1": 830})
    assert plan.since_unix is None  # no time filter — reach past the routine window
    assert plan.max_pages == 2  # newest-first, so a small gap is on page one
    assert "833" in plan.reason and "830" in plan.reason


def test_a_form_reporting_zero_while_we_hold_leads_is_still_swept() -> None:
    """Observed in prod: form 994164862988245 reports leads_count=0 holding 203 leads.

    Gating the sweep on leads_count would blind us to exactly the forms whose
    bookkeeping is broken, so this must still get the routine window.
    """
    [plan] = planned([form("f1", leads=0)], {"f1": 203})
    assert plan.reason == "routine"
    assert plan.since_unix == NOW - DAY


def test_missing_leads_count_falls_back_to_routine() -> None:
    [plan] = planned([form("f1", leads=None)], {"f1": 5})
    assert plan.reason == "routine"


# ── the run loop ────────────────────────────────────────────────────────────


class FakeSession:
    """Duck-typed AsyncSession: answers the three queries the poller makes."""

    def __init__(self, owner: FakeDb) -> None:
        self._owner = owner

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> list[tuple]:
        sql = " ".join(str(stmt).split())
        if "GROUP BY form_id" in sql:
            return list(self._owner.counts.items())
        if "crm_lead_id IS NULL" in sql:
            return list(self._owner.retryable)
        if "leadgen_id = ANY" in sql:
            asked = set(params["ids"]) if params else set()
            return [(i,) for i in self._owner.known & asked]
        raise AssertionError(f"unexpected query: {sql}")

    async def scalar(self, stmt: Any, params: dict[str, Any] | None = None) -> bool:
        assert "pg_try_advisory_xact_lock" in str(stmt)
        return self._owner.lock_free

    async def commit(self) -> None:
        self._owner.commits += 1


class FakeDb:
    def __init__(
        self,
        *,
        counts: dict[str, int] | None = None,
        retryable: list[tuple[str, str | None]] | None = None,
        known: set[str] | None = None,
        lock_free: bool = True,
    ) -> None:
        self.counts = counts or {}
        self.retryable = retryable or []
        self.known = known or set()
        self.lock_free = lock_free
        self.commits = 0

    def __call__(self) -> FakeSession:
        return FakeSession(self)


class FakeResolver:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.ingested: list[tuple[str, str | None, bool]] = []
        self._fail = fail or set()

    async def ingest_and_record(
        self, _session: Any, *, leadgen_id: str, form_id: str | None, raw: Any = None
    ) -> bool:
        self.ingested.append((leadgen_id, form_id, raw is not None))
        return leadgen_id not in self._fail


def lead(lid: str, ts: str = "2026-08-20T10:00:00+0000") -> dict[str, Any]:
    return {"id": lid, "created_time": ts, "field_data": []}


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch):
    """Build a LeadPoller with Graph + DB + resolver replaced by fakes."""

    def _wire(
        *,
        forms: list[dict[str, Any]],
        leads_by_form: dict[str, list[dict[str, Any]]],
        db: FakeDb,
        settings: SimpleNamespace | None = None,
        fail: set[str] | None = None,
    ) -> tuple[LeadPoller, FakeResolver, list[tuple[str, int | None, int]]]:
        calls: list[tuple[str, int | None, int]] = []

        async def fake_list_forms() -> list[dict[str, Any]]:
            return forms

        async def fake_poll(
            form_id: str, since_unix: int | None = None, *, max_pages: int = 100
        ) -> list[dict[str, Any]]:
            calls.append((form_id, since_unix, max_pages))
            return leads_by_form.get(form_id, [])

        monkeypatch.setattr(poller_mod, "list_forms", fake_list_forms)
        monkeypatch.setattr(poller_mod, "poll_form_leads", fake_poll)
        monkeypatch.setattr(poller_mod, "get_settings", lambda: settings or fake_settings())
        monkeypatch.setattr("meta_ads.db.async_session_maker", db, raising=False)

        p = LeadPoller()
        resolver = FakeResolver(fail=fail)
        p._resolver = resolver  # type: ignore[assignment]
        return p, resolver, calls

    return _wire


async def test_recovers_a_lead_the_webhook_never_delivered(wire) -> None:
    db = FakeDb(counts={"f1": 2}, known={"known1"})
    p, resolver, _ = wire(
        forms=[form("f1", leads=2)],
        leads_by_form={"f1": [lead("known1"), lead("missed1")]},
        db=db,
    )

    out = await p.run()

    assert [(lid, used_raw) for lid, _f, used_raw in resolver.ingested] == [("missed1", True)]
    assert out.recovered == 1 and out.failed == 0
    assert db.commits == 1


async def test_leads_already_recorded_are_left_alone(wire) -> None:
    db = FakeDb(counts={"f1": 2}, known={"a", "b"})
    p, resolver, _ = wire(
        forms=[form("f1", leads=2)], leads_by_form={"f1": [lead("a"), lead("b")]}, db=db
    )

    out = await p.run()

    assert resolver.ingested == []
    assert out.recovered == 0
    assert db.commits == 0  # nothing to write, so no transaction was opened


async def test_failed_rows_are_retried_and_reuse_the_polled_object(wire) -> None:
    """A row recorded without a crm_lead_id gets another go — a 422 is no longer terminal."""
    db = FakeDb(counts={"f1": 1}, retryable=[("stuck1", "f1")], known={"stuck1"})
    p, resolver, _ = wire(
        forms=[form("f1", leads=1)], leads_by_form={"f1": [lead("stuck1")]}, db=db
    )

    out = await p.run()

    # Not double-ingested as a "recovery" (it is known), retried once, and the
    # sweep's own lead object was reused instead of a second Graph call.
    assert resolver.ingested == [("stuck1", "f1", True)]
    assert out.retried == 1 and out.recovered == 0


async def test_retry_without_a_polled_object_resolves_from_graph(wire) -> None:
    db = FakeDb(counts={}, retryable=[("old1", "f9")])
    p, resolver, _ = wire(forms=[], leads_by_form={}, db=db)

    out = await p.run()

    assert resolver.ingested == [("old1", "f9", False)]  # raw=None -> resolve_lead
    assert out.retried == 1


async def test_a_failed_ingest_is_counted_not_raised(wire) -> None:
    db = FakeDb(counts={"f1": 0}, known=set())
    p, resolver, _ = wire(
        forms=[form("f1", leads=1)],
        leads_by_form={"f1": [lead("bad1")]},
        db=db,
        fail={"bad1"},
    )

    out = await p.run()

    assert out.failed == 1 and out.recovered == 0


async def test_nothing_is_ingested_while_the_resolver_holds_the_lock(wire) -> None:
    db = FakeDb(counts={"f1": 0}, lock_free=False)
    p, resolver, _ = wire(
        forms=[form("f1", leads=1)], leads_by_form={"f1": [lead("missed1")]}, db=db
    )

    out = await p.run()

    assert resolver.ingested == []  # deferred to the next tick, never raced
    assert out.recovered == 0 and db.commits == 0


async def test_one_broken_form_does_not_sink_the_sweep(wire, monkeypatch) -> None:
    db = FakeDb(counts={"f1": 1, "f2": 1}, known=set())
    p, resolver, _ = wire(
        forms=[form("f1", leads=1), form("f2", leads=1)],
        leads_by_form={"f2": [lead("m2")]},
        db=db,
    )

    async def explode(form_id: str, since_unix: int | None = None, *, max_pages: int = 100):
        if form_id == "f1":
            raise RuntimeError("graph is down for this form")
        return [lead("m2")]

    monkeypatch.setattr(poller_mod, "poll_form_leads", explode)

    out = await p.run()

    assert out.forms_polled == 1  # f1 failed, f2 still swept
    assert [lid for lid, *_ in resolver.ingested] == ["m2"]


async def test_disabled_poller_touches_nothing(wire) -> None:
    db = FakeDb(counts={"f1": 0})
    p, resolver, calls = wire(
        forms=[form("f1", leads=5)],
        leads_by_form={"f1": [lead("x")]},
        db=db,
        settings=fake_settings(fb_lead_poll_enabled=False),
    )

    out = await p.run()

    assert calls == [] and resolver.ingested == []
    assert out == poller_mod.PollOutcome()
