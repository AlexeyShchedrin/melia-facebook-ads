"""form answers — labeling lead fields against the form's questions, plus the questions cache (fakes only)."""

from __future__ import annotations

from typing import Any

import pytest

import meta_ads.ingest.form_answers as fa
import meta_ads.ingest.resolver as resolver_mod
from meta_ads.ingest.form_answers import FormQuestionsCache, build_answers, is_answer_key
from meta_ads.ingest.resolver import build_crm_payload

QUESTIONS: list[dict[str, Any]] = [
    {"key": "full_name", "label": "Full name", "type": "FULL_NAME"},
    {"key": "phone", "label": "Phone number", "type": "PHONE"},
    {"key": "email", "label": "Email", "type": "EMAIL"},
    {
        "key": "budget",
        "label": "Purchase budget",
        "type": "CUSTOM",
        "options": [
            {"key": "budget_1", "value": "Up to €250,000"},
            {"key": "budget_2", "value": "€250,000–400,000"},
        ],
    },
    {
        "key": "timing",
        "label": "When do you plan to buy",
        "type": "CUSTOM",
        "options": [{"key": "timing_1", "value": "Within 3 months"}],
    },
    {"key": "note", "label": "Anything else?", "type": "CUSTOM"},
]

# What field_data_to_map produces for such a form: the form's own keys plus the
# phone -> phone_number alias.
FIELDS = {
    "full_name": "Ana",
    "phone": "+38267000000",
    "phone_number": "+38267000000",
    "email": "ana@example.com",
    "timing": "timing_1",
    "budget": "budget_2",
    "note": "call me after 6",
}


# ── build_answers ───────────────────────────────────────────────────────────


def test_identity_and_system_keys_are_not_answers() -> None:
    for key in (
        "full_name",
        "first_name",
        "last_name",
        "email",
        "work_email",
        "e-mail",
        "phone",
        "phone_number",
        "work_phone_number",
        "Phone_Number",
        "inbox_url",
    ):
        assert not is_answer_key(key), key
    for key in ("budget", "timing", "purpose", "deal_type", "expo_meeting", "city"):
        assert is_answer_key(key), key


def test_answers_follow_the_form_order_with_both_labels() -> None:
    out = build_answers(FIELDS, QUESTIONS)
    assert [a["key"] for a in out] == ["budget", "timing", "note"]
    assert out[0] == {
        "key": "budget",
        "label": "Purchase budget",
        "value_key": "budget_2",
        "value_label": "€250,000–400,000",
    }
    assert out[1]["value_label"] == "Within 3 months"
    # A free-text question echoes what the visitor typed.
    assert out[2] == {
        "key": "note",
        "label": "Anything else?",
        "value_key": "call me after 6",
        "value_label": "call me after 6",
    }


def test_unknown_option_key_leaves_the_value_label_empty() -> None:
    """The Lead Ads Testing Tool answers choice questions with dummy text."""
    [a] = build_answers({"budget": "<test lead: dummy data for budget>"}, QUESTIONS)
    assert a["label"] == "Purchase budget"
    assert a["value_key"] == "<test lead: dummy data for budget>"
    assert a["value_label"] is None


def test_keys_the_form_does_not_define_are_appended_unlabeled() -> None:
    out = build_answers({"expo_meeting": "meeting_4", "budget": "budget_1"}, QUESTIONS)
    assert [a["key"] for a in out] == ["budget", "expo_meeting"]
    assert out[1] == {
        "key": "expo_meeting",
        "label": None,
        "value_key": "meeting_4",
        "value_label": None,
    }


def test_without_questions_every_answer_ships_unlabeled() -> None:
    out = build_answers(FIELDS, None)
    assert [a["key"] for a in out] == ["timing", "budget", "note"]
    assert all(a["label"] is None and a["value_label"] is None for a in out)


def test_identity_only_form_has_no_answers() -> None:
    fields = {"full_name": "A", "phone_number": "+1", "inbox_url": "https://x"}
    assert build_answers(fields, None) == []


# ── FormQuestionsCache ──────────────────────────────────────────────────────


class _Nested:
    async def __aenter__(self) -> _Nested:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def first(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class FakeSession:
    """Duck-typed AsyncSession for the two statements the cache issues."""

    def __init__(self, stored: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.stored = stored
        self.fail = fail
        self.reads = 0
        self.writes: list[dict[str, Any] | None] = []

    def begin_nested(self) -> _Nested:
        return _Nested()

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _Result:
        if self.fail:
            raise RuntimeError("db down")
        sql = " ".join(str(stmt).split())
        if sql.startswith("SELECT questions FROM meta.leadgen_form_questions"):
            self.reads += 1
            return _Result([(self.stored,)] if self.stored is not None else [])
        if sql.startswith("INSERT INTO meta.leadgen_form_questions"):
            self.writes.append(params)
            return _Result([])
        raise AssertionError(f"unexpected statement: {sql}")


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch):
    """Replace the Graph read; returns (call log, state) so a test can make it fail."""
    calls: list[tuple[str, str | None]] = []
    state = {"fail": False}

    async def fake_get(form_id: str, page_id: str | None = None) -> dict[str, Any]:
        calls.append((form_id, page_id))
        if state["fail"]:
            raise RuntimeError("Graph 400: (#17) rate limit")
        return {"id": form_id, "name": f"LF_{form_id}", "locale": "en_US", "questions": QUESTIONS}

    monkeypatch.setattr(fa, "get_form_questions", fake_get)
    return calls, state


async def test_cache_reads_the_db_before_graph(graph) -> None:
    calls, _ = graph
    session = FakeSession(stored=QUESTIONS)
    cache = FormQuestionsCache()
    assert await cache.get(session, "f1", None) == QUESTIONS
    assert calls == [] and session.reads == 1
    # Memoized: a second lead of the same form touches neither DB nor Graph.
    assert await cache.get(session, "f1", None) == QUESTIONS
    assert session.reads == 1


async def test_cache_fetches_once_then_persists_and_memoizes(graph) -> None:
    calls, _ = graph
    session = FakeSession()
    cache = FormQuestionsCache()
    assert await cache.get(session, "f1", "PAGE2") == QUESTIONS
    assert calls == [("f1", "PAGE2")]
    [row] = session.writes
    assert row is not None and row["f"] == "f1" and row["p"] == "PAGE2" and row["n"] == "LF_f1"
    assert "budget_2" in row["q"]
    assert await cache.get(session, "f1", "PAGE2") == QUESTIONS
    assert calls == [("f1", "PAGE2")] and len(session.writes) == 1


async def test_graph_failure_yields_none_and_is_not_memoized(graph) -> None:
    calls, state = graph
    state["fail"] = True
    cache = FormQuestionsCache()
    assert await cache.get(FakeSession(), "f1", None) is None
    assert await cache.get(FakeSession(), "f1", None) is None
    assert len(calls) == 2  # tried again for the next lead
    state["fail"] = False
    assert await cache.get(FakeSession(), "f1", None) == QUESTIONS


async def test_db_failure_does_not_lose_the_questions(graph) -> None:
    calls, _ = graph
    cache = FormQuestionsCache()
    assert await cache.get(FakeSession(fail=True), "f1", None) == QUESTIONS
    assert len(calls) == 1


async def test_no_session_means_memo_plus_graph_only(graph) -> None:
    calls, _ = graph
    cache = FormQuestionsCache()
    assert await cache.get(None, "f1", None) == QUESTIONS
    assert await cache.get(None, "f1", None) == QUESTIONS
    assert len(calls) == 1


# ── the payload ─────────────────────────────────────────────────────────────


async def test_payload_carries_fields_and_labeled_answers(graph, monkeypatch) -> None:
    async def names(*_a: Any, **_k: Any) -> dict[str, str]:
        return {"form_name": "LF_EN"}

    monkeypatch.setattr(resolver_mod, "_names_for", names)
    monkeypatch.setattr(resolver_mod, "_form_questions", FormQuestionsCache())
    raw = {
        "form_id": "f1",
        "created_time": "2026-09-02T10:00:00+0000",
        "field_data": [
            {"name": "full_name", "values": ["Ana"]},
            {"name": "phone", "values": ["+38267000000"]},
            {"name": "budget", "values": ["budget_2"]},
        ],
    }
    payload = await build_crm_payload("L1", raw, None, None, session=FakeSession())
    assert payload["fields"] == {
        "full_name": "Ana",
        "phone": "+38267000000",
        "phone_number": "+38267000000",
        "budget": "budget_2",
    }
    assert payload["answers"] == [
        {
            "key": "budget",
            "label": "Purchase budget",
            "value_key": "budget_2",
            "value_label": "€250,000–400,000",
        }
    ]
    assert payload["form_name"] == "LF_EN"


async def test_identity_only_lead_has_no_answers_key(graph, monkeypatch) -> None:
    async def names(*_a: Any, **_k: Any) -> dict[str, str]:
        return {}

    monkeypatch.setattr(resolver_mod, "_names_for", names)
    raw = {"form_id": "f1", "field_data": [{"name": "email", "values": ["a@b.c"]}]}
    payload = await build_crm_payload("L2", raw, None, None, session=FakeSession())
    assert "answers" not in payload
