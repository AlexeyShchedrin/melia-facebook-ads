"""Smoke tests — import graph, config, and the CAPI anti-contamination invariant."""

from __future__ import annotations

from meta_ads import __version__
from meta_ads.conversions.hashing import hash_email, hash_phone
from meta_ads.conversions.taxonomy import OUTBOX_KIND_SKIP, OUTBOX_KIND_TO_EVENT


def test_version() -> None:
    assert __version__


def test_config_imports() -> None:
    from meta_ads.config import get_settings

    s = get_settings()
    assert s.meta_api_version.startswith("v")
    assert s.graph_base.endswith(s.meta_api_version)


def test_lead_submitted_is_skipped() -> None:
    # Meta already knows the form submit — sending it via CAPI would double-count.
    assert "lead_submitted" in OUTBOX_KIND_SKIP
    assert "lead_submitted" not in OUTBOX_KIND_TO_EVENT


def test_offer_maps_to_lead_offer_sent() -> None:
    event_name, value = OUTBOX_KIND_TO_EVENT["lifecycle_offer"]
    assert event_name == "lead_offer_sent"
    assert value is not None
    assert "lifecycle_offer" not in OUTBOX_KIND_SKIP


def test_lost_maps_to_lead_lost_with_reason_property() -> None:
    from datetime import UTC, datetime

    from meta_ads.channels.base import ConversionEvent
    from meta_ads.channels.meta.conversions import MetaCapiUploader

    event_name, value = OUTBOX_KIND_TO_EVENT["lifecycle_lost"]
    assert event_name == "lead_lost"
    assert value is None  # negative signal carries no value

    ev = ConversionEvent(
        action_name="lead_lost",
        event_time=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        meta_lead_id="123",
        properties={"loss_reason": "misclick"},
    )
    m = MetaCapiUploader("ds1")._to_meta_event(ev)
    assert m["custom_data"] == {"loss_reason": "misclick"}  # no value key


def test_hashing_is_normalized() -> None:
    # Same identity, different formatting → identical hash (Meta match rules).
    assert hash_email(" Foo@Bar.COM ") == hash_email("foo@bar.com")
    assert hash_phone("+382 (67) 123-456") == hash_phone("38267123456")


def test_worker_imports() -> None:
    # The whole worker import graph must resolve (jobs, listen, drains).
    from meta_ads.worker import main

    assert main.main


# ─── pipeline A pure-logic (no network / no DB) ──────────────────────


def test_spec_hash_is_order_independent() -> None:
    from meta_ads.channels.meta.campaigns import spec_hash

    a = spec_hash({"x": 1, "y": 2})
    b = spec_hash({"y": 2, "x": 1})
    assert a == b and len(a) == 64


def test_eur_to_minor() -> None:
    from decimal import Decimal

    from meta_ads.channels.meta.campaigns import eur_to_minor

    assert eur_to_minor(Decimal("5")) == 500
    assert eur_to_minor(Decimal("12.34")) == 1234


def test_object_story_spec_lead_cta() -> None:
    from meta_ads.channels.meta.creatives import build_object_story_spec

    spec = build_object_story_spec(page_id="P", lead_gen_form_id="F", message="hi", image_hash="H")
    assert spec["page_id"] == "P"
    cta = spec["link_data"]["call_to_action"]
    assert cta["type"] == "SIGN_UP"  # "LEAD" is rejected by Meta for lead creatives
    assert cta["value"]["lead_gen_form_id"] == "F"


def test_capi_event_shape() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from meta_ads.channels.base import ConversionEvent
    from meta_ads.channels.meta.conversions import MetaCapiUploader

    ev = ConversionEvent(
        action_name="lead_qualified",
        event_time=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        value_eur=Decimal("20.00"),
        hashed_email="e" * 64,
        meta_lead_id="1363055189106002",
        lead_id=3870,
        order_id="crm-outbox-42",
    )
    m = MetaCapiUploader("ds1")._to_meta_event(ev)
    assert m["event_name"] == "lead_qualified"
    assert m["action_source"] == "system_generated"
    assert m["user_data"]["lead_id"] == "1363055189106002"  # THE join key (PLAN §5)
    assert m["event_id"] == "crm-outbox-42"  # CAPI dedup
    assert m["custom_data"] == {"value": 20.0, "currency": "EUR"}


def test_object_story_spec_needs_a_creative() -> None:
    import pytest

    from meta_ads.channels.meta.creatives import build_object_story_spec

    with pytest.raises(ValueError):
        build_object_story_spec(page_id="P", lead_gen_form_id="F", message="hi")
