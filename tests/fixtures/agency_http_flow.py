"""Synthetic cross-repository test driver. Graph is the only external boundary replaced."""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
assert not (ROOT / ".env").exists(), "The contract fixture requires a checkout without provider secrets"
import meta_ads  # noqa: E402

assert Path(meta_ads.__file__).resolve().parent == ROOT / "src" / "meta_ads"
from meta_ads.channels.meta.client import PAGE, GraphClient  # noqa: E402
from meta_ads.config import get_settings  # noqa: E402
from meta_ads.ingest import poller, resolver  # noqa: E402
from meta_ads.security import hmac_sign  # noqa: E402

settings = get_settings()
url = make_url(settings.fb_database_url)
assert url.host in {"localhost", "127.0.0.1"} and url.database.startswith("kvadra_test_")
assert settings.crm_ingest_url.startswith(("http://127.0.0.1:", "http://localhost:"))
data = json.loads(sys.stdin.read() or "{}")


def initialize():
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS meta"))
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(config, "head")
    finally:
        engine.dispose()


async def run_flow():
    lead_id, form_id, page_id = data["leadgenId"], data["formId"], data["pageId"]
    raw = {"id": lead_id, "form_id": form_id, "created_time": "2026-10-23T12:00:00+0000",
           "field_data": [{"name": key, "values": [value]} for key, value in data["fields"].items()]}

    def graph_response(request):
        assert request.method == "GET" and request.url.host == "graph.facebook.com"
        assert request.url.params["access_token"] == "synthetic-page-token"
        path = request.url.path.removeprefix(f"/{settings.meta_api_version}/")
        if data.get("providerError"):
            return httpx.Response(400, json={"error": {"code": 190, "message": "synthetic expired token"}})
        if path == lead_id:
            return httpx.Response(200, json=raw)
        if path == form_id:
            return httpx.Response(200, json={"id": form_id, "name": "Synthetic agency form", "questions": []})
        if path == f"{page_id}/leadgen_forms":
            return httpx.Response(200, json={"data": [{"id": form_id, "status": "ACTIVE", "leads_count": 0}]})
        if path == f"{form_id}/leads":
            return httpx.Response(200, json={"data": [raw]})
        # A prior failed fixture can also be selected by the real retry scan.
        return httpx.Response(400, json={"error": {"code": 100, "message": "no synthetic Graph fixture"}})

    async def graph_for_provider(provider, asset_id=None):
        assert provider == PAGE and asset_id == page_id
        graph = GraphClient("synthetic-page-token")
        await graph._http.aclose()
        graph._http = httpx.AsyncClient(base_url=graph._base, transport=httpx.MockTransport(graph_response))
        return graph

    # Only provider credentials and Graph network responses are synthetic.
    # Real GraphClient request/error handling, caches and intake code still run.
    GraphClient.for_provider = staticmethod(graph_for_provider)
    if data.get("mode", "callback") == "callback":
        body = json.dumps({"object": "page", "entry": [{"id": page_id, "changes": [
            {"field": "leadgen", "value": {"leadgen_id": lead_id, "form_id": form_id, "page_id": page_id}}]}]}, separators=(",", ":")).encode()
        endpoint = settings.crm_ingest_url.replace("/lead-ingest", "/lead-webhook")
        async with httpx.AsyncClient() as client:
            response = await client.post(endpoint, content=body, headers={"content-type": "application/json",
                "x-hub-signature-256": "sha256=" + hmac_sign(body, os.environ["META_APP_SECRET"])})
            response.raise_for_status()
        outcome = await resolver.InboundResolver().run()
    else:
        outcome = await poller.LeadPoller().run()
    from meta_ads.db import async_session_maker

    async with async_session_maker() as session:
        row = (await session.execute(text("SELECT result_kind, crm_lead_id, agency_inquiry_id::text, agency_lead_id::text, match_status, error, attempts FROM meta.processed_inbound WHERE leadgen_id = :id"), {"id": lead_id})).mappings().one()
    return {"outcome": vars(outcome), "receipt": dict(row)}


if sys.argv[1] == "initialize":
    initialize()
    print(json.dumps({"ok": True}))
else:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(json.dumps(asyncio.run(run_flow())))
