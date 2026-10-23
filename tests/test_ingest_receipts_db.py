"""Actual PostgreSQL migration and receipt races; opt in to a synthetic cluster only."""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from meta_ads.config import get_settings
from meta_ads.ingest.contract import CrmResult
from meta_ads.ingest.poller import LeadPoller
from meta_ads.ingest.resolver import InboundResolver, _Inbound

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.WindowsSelectorEventLoopPolicy() if sys.platform == "win32" else asyncio.DefaultEventLoopPolicy()


@pytest.fixture(params=["fresh", "legacy_0004"])
def database(request, monkeypatch):
    configured = os.environ.get("AGENCY_META_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("AGENCY_META_TEST_DATABASE_URL is required for isolated PostgreSQL tests")
    url = make_url(configured).set(drivername="postgresql+psycopg")
    assert url.host in {"localhost", "127.0.0.1"} and url.database == "postgres"
    name = f"kvadra_test_meta_{uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    owned_url = url.set(database=name)
    engine = create_engine(owned_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA meta"))
            if request.param == "legacy_0004":
                # Exact target-table shape at released 0004; successful integer
                # receipts and a failed attempt must survive 0005 unchanged.
                connection.execute(text("""CREATE TABLE meta.processed_inbound (
                    leadgen_id varchar(32) PRIMARY KEY, form_id varchar(64), page_id varchar(64),
                    crm_lead_id bigint, error text, attempts integer NOT NULL,
                    processed_at timestamptz NOT NULL DEFAULT now())"""))
                connection.execute(text("CREATE INDEX ix_meta_processed_inbound_form ON meta.processed_inbound(form_id)"))
                connection.execute(text("INSERT INTO meta.processed_inbound (leadgen_id,crm_lead_id,attempts) VALUES ('old',42,2)"))
                connection.execute(text("INSERT INTO meta.processed_inbound (leadgen_id,error,attempts) VALUES ('oldfailed','old failure',5)"))
                assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='meta' AND table_name='processed_inbound' AND data_type='uuid'")) == 0
                connection.execute(text("CREATE TABLE meta.alembic_version (version_num varchar(32) PRIMARY KEY)"))
                connection.execute(text("INSERT INTO meta.alembic_version VALUES ('0004_leadgen_form_questions')"))
        monkeypatch.setenv("FB_DATABASE_URL", owned_url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(cfg, "head")
        yield owned_url, engine, request.param
    finally:
        engine.dispose()
        get_settings.cache_clear()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


async def test_receipts_survive_failed_races_and_agency_conflicts_are_terminal(database):
    url, engine, baseline = database
    if baseline == "legacy_0004":
        with engine.connect() as connection:
            row = connection.execute(text("SELECT crm_lead_id, result_kind, attempts FROM meta.processed_inbound WHERE leadgen_id='old'")).one()
            assert tuple(row) == (42, "project", 2)
    async_engine = create_async_engine(url)
    resolver = InboundResolver()
    inquiry_id = UUID("11111111-1111-4111-8111-111111111111")
    try:
        async with AsyncSession(async_engine) as session:
            agency = _Inbound(0, "999", "777", "456")
            project = _Inbound(0, "998", "776", "456")
            failed = _Inbound(0, "997", "775", "456")
            await resolver._record(session, agency, result=CrmResult("agency", agency_inquiry_id=inquiry_id, match_status="conflict"), error=None)
            await resolver._record(session, agency, result=None, error="crm_http_503")
            await resolver._record(session, project, result=None, error="crm_http_503")
            await resolver._record(session, project, result=CrmResult("project", crm_lead_id=43), error=None)
            await resolver._record(session, project, result=None, error="delivery_timeout")
            await resolver._record(session, failed, result=None, error="provider_http_400_code_190")
            await session.commit()
            agency_row = (await session.execute(text("SELECT * FROM meta.processed_inbound WHERE leadgen_id='999'"))).mappings().one()
            assert agency_row["agency_inquiry_id"] == inquiry_id
            assert agency_row["agency_lead_id"] is None and agency_row["crm_lead_id"] is None
            assert agency_row["error"] is None and agency_row["connection_key"] == "meta:123:456"
            assert await session.scalar(text("SELECT crm_lead_id FROM meta.processed_inbound WHERE leadgen_id='998'")) == 43
            retry = await LeadPoller()._retryable(session)
            assert retry == [("997", "775", "456")]
            assert await resolver.ingest_and_record(session, leadgen_id="999", form_id="777", page_id="456") is True
            # Explicit manual retry authorizes one extra attempt after exhaustion.
            await session.execute(text("UPDATE meta.processed_inbound SET attempts=20 WHERE leadgen_id='997'"))
            await session.execute(text("CREATE SCHEMA ads_contract"))
            await session.execute(text("CREATE TABLE ads_contract.test_retry (leadgen_id text, connection_key text, page_id text, form_id text, requested_at timestamptz)"))
            await session.execute(text("CREATE VIEW ads_contract.v_meta_retry_requests AS SELECT * FROM ads_contract.test_retry"))
            await session.execute(text("INSERT INTO ads_contract.test_retry VALUES ('997','meta:123:456','456','775',clock_timestamp())"))
            await session.commit()
            assert await LeadPoller()._retryable(session) == [("997", "775", "456")]
            await resolver._record(session, failed, result=None, error="crm_http_503")
            await session.commit()
            assert await LeadPoller()._retryable(session) == []
            # An old worker writing its integer-only columns is still supported.
            await session.execute(text("INSERT INTO meta.processed_inbound (leadgen_id,crm_lead_id,attempts) VALUES ('legacy_writer',44,1)"))
            await session.commit()
    finally:
        await async_engine.dispose()
