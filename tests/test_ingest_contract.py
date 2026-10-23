"""The worker accepts durable project/agency receipts, never an empty HTTP success."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

import meta_ads.channels.meta.client as graph_client
import meta_ads.ingest.resolver as resolver
from meta_ads.ingest.contract import parse_crm_result

INQUIRY = "11111111-1111-4111-8111-111111111111"
LEAD = "22222222-2222-4222-8222-222222222222"


def test_project_receipts_keep_integer_identity():
    for payload in [{"ok": True, "leadId": 42}, {"ok": True, "kind": "project", "leadId": 42}]:
        result = parse_crm_result(payload)
        assert result.kind == "project" and result.crm_lead_id == 42
        assert result.agency_inquiry_id is None


@pytest.mark.parametrize("lead_id,status", [(LEAD, "matched"), (None, "conflict"), (None, "unresolved")])
def test_agency_receipt_accepts_a_durable_inquiry_without_a_client(lead_id, status):
    result = parse_crm_result({"ok": True, "kind": "agency", "inquiryId": INQUIRY,
                               "leadId": lead_id, "matchStatus": status})
    assert result.crm_lead_id is None
    assert result.agency_inquiry_id == UUID(INQUIRY)
    assert result.agency_lead_id == (UUID(lead_id) if lead_id else None)


@pytest.mark.parametrize("payload", [
    {}, {"ok": False, "leadId": 42}, {"ok": True}, {"ok": True, "leadId": True},
    {"ok": True, "leadId": "42"}, {"ok": True, "leadId": 0},
    {"ok": True, "kind": "unknown", "leadId": 42},
    {"ok": True, "kind": "agency", "leadId": LEAD},
    {"ok": True, "kind": "agency", "inquiryId": "bad", "leadId": None, "matchStatus": "conflict"},
    {"ok": True, "kind": "agency", "inquiryId": INQUIRY, "leadId": None, "matchStatus": "matched"},
    {"ok": True, "kind": "agency", "inquiryId": INQUIRY, "leadId": LEAD, "matchStatus": "conflict"},
])
def test_incomplete_or_ambiguous_success_is_not_acknowledged(payload):
    with pytest.raises(ValueError):
        parse_crm_result(payload)


async def test_payload_uses_trusted_page_and_app_for_the_same_poll_and_callback_identity(monkeypatch):
    async def names(*args, **kwargs):
        return {}

    class Questions:
        async def get(self, *args):
            return None

    monkeypatch.setattr(resolver, "_names_for", names)
    monkeypatch.setattr(resolver, "_form_questions", Questions())
    monkeypatch.setattr(resolver, "get_settings", lambda: SimpleNamespace(meta_app_id="123", meta_page_id="456"))
    raw = {"id": "999", "form_id": "777", "page_id": "untrusted", "field_data": []}
    callback = await resolver.build_crm_payload("999", raw, "777", "456")
    poll = await resolver.build_crm_payload("999", raw, "777", "456")
    assert callback == poll
    assert callback["contract_version"] == 2
    assert callback["page_id"] == "456"
    assert callback["connection_key"] == "meta:123:456"
    with pytest.raises(ValueError, match="form"):
        await resolver.build_crm_payload("999", raw, "different", "456")
    with pytest.raises(ValueError, match="lead"):
        await resolver.build_crm_payload("other", raw, "777", "456")


@pytest.mark.parametrize("exception,category", [
    (httpx.ConnectError, "delivery_unavailable"),
    (httpx.ReadTimeout, "delivery_timeout"),
])
async def test_unavailable_graph_is_retryable_without_logging_provider_details(monkeypatch, caplog, exception, category):
    settings = SimpleNamespace(meta_app_id="123", meta_page_id="456", graph_base="https://graph.facebook.com/v25.0")
    monkeypatch.setattr(resolver, "get_settings", lambda: settings)
    monkeypatch.setattr(graph_client, "get_settings", lambda: settings)

    def unavailable(request):
        assert request.url.params["access_token"] == "synthetic-sensitive-token"
        raise exception("provider included person@example.invalid and synthetic-sensitive-token", request=request)

    async def graph_for_provider(provider, asset_id=None):
        assert provider == graph_client.PAGE and asset_id == "456"
        graph = graph_client.GraphClient("synthetic-sensitive-token")
        await graph._http.aclose()
        graph._http = httpx.AsyncClient(base_url=graph._base, transport=httpx.MockTransport(unavailable))
        return graph

    monkeypatch.setattr(graph_client.GraphClient, "for_provider", staticmethod(graph_for_provider))
    worker = resolver.InboundResolver()
    record = AsyncMock()
    post = AsyncMock(side_effect=AssertionError("Unresolved provider data must not reach the CRM"))
    monkeypatch.setattr(worker, "_record", record)
    monkeypatch.setattr(worker, "_post_to_crm", post)
    session = SimpleNamespace(scalar=AsyncMock(return_value=False))

    assert await worker.ingest_and_record(session, leadgen_id="999", form_id="777", page_id="456") is False
    record.assert_awaited_once()
    assert record.await_args.kwargs == {"result": None, "error": category}
    assert record.await_args.args[1].leadgen_id == "999"
    post.assert_not_awaited()
    assert category in caplog.text
    assert "synthetic-sensitive-token" not in caplog.text
    assert "person@example.invalid" not in caplog.text
