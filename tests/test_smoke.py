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
