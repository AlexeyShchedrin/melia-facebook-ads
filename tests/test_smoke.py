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


def test_object_story_spec_needs_a_creative() -> None:
    import pytest

    from meta_ads.channels.meta.creatives import build_object_story_spec

    with pytest.raises(ValueError):
        build_object_story_spec(page_id="P", lead_gen_form_id="F", message="hi")
