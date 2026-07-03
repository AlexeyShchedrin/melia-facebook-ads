"""One-off: re-ingest all leads of the six 2026-07 HI-OTP forms straight from
Graph (the relay queue rows are gone), through the same resolver path, so the
CRM dedup+backfill fills the phones lost to the phone/phone_number key bug."""
import asyncio

from meta_ads.channels.meta.leads import field_data_to_map, poll_form_leads
from meta_ads.db import async_session_maker
from meta_ads.ingest.resolver import InboundResolver, _Inbound, _names_for

FORMS = [
    "1342846111284734", "1600030904874809", "1001277082895735",
    "1990944504878103", "1748082802861437", "1317603176749048",
]


async def main() -> None:
    r = InboundResolver()
    ok = fail = 0
    async with async_session_maker() as session:
        for fid in FORMS:
            for raw in await poll_form_leads(fid):
                lid = raw["id"]
                try:
                    names = await _names_for(raw.get("ad_id"), fid)
                    lead = {
                        "leadgen_id": lid,
                        "form_id": fid,
                        "created_time": raw.get("created_time"),
                        "campaign_id": raw.get("campaign_id"),
                        "adset_id": raw.get("adset_id"),
                        "ad_id": raw.get("ad_id"),
                        "platform": raw.get("platform"),
                        "is_organic": raw.get("is_organic"),
                        **names,
                        "fields": field_data_to_map(raw.get("field_data", [])),
                    }
                    crm = await r._post_to_crm(lead)
                    await r._record(session, _Inbound(id=0, leadgen_id=lid, form_id=fid), crm_lead_id=crm, error=None)
                    ok += 1
                    print(f"{fid} {lid} -> crm_lead {crm}", flush=True)
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    print(f"{fid} {lid} FAILED: {e}", flush=True)
        await session.commit()
    print(f"done: ok={ok} fail={fail}")


asyncio.run(main())
